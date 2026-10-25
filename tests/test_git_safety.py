"""The importer commits only with --commit (or git_commit = true in the library's
config file) and pushes only with --push (or git_push = true).

git is replaced by a recorder (no repository, nothing is committed or pushed),
and the importer runs in this process so the recorder sees every call."""
import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import libtest_helpers as H
import kicad_part_importer as kpi


class GitCallsBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.lib = H.make_library(t / "partlib")
        self.zip = t / "p.zip"
        H.ti_zip(self.zip)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args, inputs=()):
        """Run main() in-process; return (exit code, list of git command lines)."""
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        argv = ["--library-root", str(self.lib)] + [str(a) for a in args]
        code = 0
        with mock.patch.dict(os.environ, H.clean_env(), clear=True), \
                mock.patch.object(kpi.subprocess, "run", side_effect=fake_run), \
                mock.patch("builtins.input", side_effect=list(inputs)), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                kpi.main(argv)
            except SystemExit as exc:
                code = exc.code or 0
        return code, [c for c in calls if c and c[0] == "git"]


class GitCalls(GitCallsBase):
    def test_planned_import_commits_written_files_and_does_not_push(self):
        code, git = self.run_main(self.zip, "--category", "ics_general", "--link-3d", "--yes", "--commit")
        self.assertEqual(code, 0)
        self.assertEqual([c[1] for c in git], ["add", "commit"])
        self.assertIn("lib_sym/lib_ics_general.kicad_sym", git[0])
        self.assertNotIn(".", git[0][2:])  # exactly the written files, not `git add .`
        self.assertFalse(any("push" in c for c in git))

    def test_prompting_import_commit_does_not_push(self):
        code, git = self.run_main(self.zip, "--commit", inputs=["4", "n"])
        self.assertEqual(code, 0)
        self.assertEqual([c[1] for c in git], ["add", "commit"])
        self.assertFalse(any("push" in c for c in git))

    def test_no_git_without_flags(self):
        for args, inputs in (((self.zip, "--category", "ics_general", "--yes"), ()),
                             (("--init-libraries",), ()),
                             ((self.zip,), ["4", "n"])):
            code, git = self.run_main(*args, inputs=inputs)
            self.assertEqual(code, 0, args)
            self.assertEqual(git, [], args)

    def test_dry_run_never_commits_or_pushes(self):
        code, git = self.run_main(self.zip, "--category", "ics_general", "--dry-run", "--commit", "--push")
        self.assertEqual(code, 0)
        self.assertEqual(git, [])

    def test_push_only_with_the_flag(self):
        code, git = self.run_main(self.zip, "--category", "ics_general", "--yes", "--commit", "--push")
        self.assertEqual(code, 0)
        self.assertEqual([c[1] for c in git], ["add", "commit", "push"])
        self.assertEqual(git[-1], ["git", "push"])

    def test_commit_messages(self):
        code, git = self.run_main("--init-libraries", "--commit")
        self.assertEqual(code, 0)
        self.assertEqual(git[1][:4], ["git", "commit", "-m", "Initialize library files"])
        code, git = self.run_main(self.zip, "--category", "ics_general", "--yes", "--commit")
        self.assertEqual(git[1][:4], ["git", "commit", "-m", "Add components from p.zip"])


class GitSettingsInTheConfigFile(GitCallsBase):
    """git_commit / git_push / git_message_prefix in the library's own config file."""

    def write_config(self, **settings):
        (self.lib / "kicad-part-importer.json").write_text(json.dumps(settings), encoding="utf-8")

    def test_config_commits_and_pushes_without_flags(self):
        self.write_config(git_commit=True, git_push=True, git_message_prefix="parts: ")
        code, git = self.run_main(self.zip, "--category", "ics_general", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual([c[1] for c in git], ["add", "commit", "push"])
        self.assertEqual(git[1][:4], ["git", "commit", "-m", "parts: Add components from p.zip"])

    def test_flags_override_the_config(self):
        self.write_config(git_commit=True, git_push=True)
        code, git = self.run_main(self.zip, "--category", "ics_general", "--yes", "--no-commit", "--no-push")
        self.assertEqual((code, git), (0, []))

    def test_default_is_off(self):
        self.write_config(git_message_prefix="parts: ")
        code, git = self.run_main(self.zip, "--category", "ics_general", "--yes")
        self.assertEqual((code, git), (0, []))

    def test_dry_run_and_check_3d_never_commit(self):
        self.write_config(git_commit=True, git_push=True)
        code, git = self.run_main(self.zip, "--category", "ics_general", "--dry-run")
        self.assertEqual((code, git), (0, []))
        code, git = self.run_main("--check-3d", "--fix-3d", "--yes", "--commit", "--push")
        self.assertEqual((code, git), (0, []))


@unittest.skipUnless(shutil.which("git"), "git not found")
class RealGit(unittest.TestCase):
    """With a real repository: the commit lands, and git's own output never
    reaches stdout under --json (it holds only the JSON report)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.lib = H.make_library(t / "partlib")
        self.zip = t / "p.zip"
        H.ti_zip(self.zip)
        self.env = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "kpi-test",
                    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "kpi-test",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-q", "-m", "empty library")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git"] + list(args), cwd=self.lib, env=H.clean_env(self.env), check=True,
                              capture_output=True, text=True).stdout

    def test_json_commit_keeps_stdout_clean(self):
        (self.lib / "kicad-part-importer.json").write_text(json.dumps({"git_message_prefix": "parts: "}),
                                                           encoding="utf-8")
        self.git("add", "kicad-part-importer.json")
        self.git("commit", "-q", "-m", "config")
        r = H.run_importer("--library", self.lib, self.zip, "--category", "ics_general", "--link-3d", "--yes",
                           "--json", "--commit", env_extra=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)  # nothing but the report on stdout
        self.assertTrue(rep["ok"])
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "parts: Add components from p.zip")
        self.assertEqual(sorted(self.git("show", "--name-only", "--format=", "HEAD").split()), sorted(rep["written"]))
        self.assertEqual(self.git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
