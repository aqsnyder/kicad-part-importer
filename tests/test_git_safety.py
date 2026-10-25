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
import zipfile
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

    def run_main(self, *args, inputs=(), env_extra=None):
        """Run main() in-process; return (exit code, list of git command lines).
        The run's stdout and stderr are left in self.out and self.err."""
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        argv = ["--library-root", str(self.lib)] + [str(a) for a in args]
        code = 0
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, H.clean_env(env_extra), clear=True), \
                mock.patch.object(kpi.subprocess, "run", side_effect=fake_run), \
                mock.patch("builtins.input", side_effect=list(inputs)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                kpi.main(argv)
            except SystemExit as exc:
                code = exc.code or 0
        self.out, self.err = out.getvalue(), err.getvalue()
        # `git check-ignore` only reads (which paths .gitignore excludes); RealGitIgnore covers it.
        return code, [c for c in calls if c and c[0] == "git" and c[1:2] != ["check-ignore"]]


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
        (self.lib / "lib_sym" / "lib_sensors.kicad_sym").unlink()  # so --init-libraries has a file to write
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


class CommitsOnlyWhatTheCommandWrote(GitCallsBase):
    """Every command commits the library files it wrote, by pathspec, and nothing
    else: not `git add .`, not a bare `git commit` that would take whatever else
    is staged, never the project's tables."""

    def test_prompting_import_commits_its_files_by_pathspec(self):
        code, git = self.run_main(self.zip, "--commit", inputs=["4", "n"])
        self.assertEqual(code, 0, self.out + self.err)
        self.assertEqual([c[1] for c in git], ["add", "commit"])
        add, commit = git
        self.assertEqual(add[:4], ["git", "add", "-f", "--"])  # -f: ignored paths are filtered out before
        self.assertNotIn(".", add[4:])
        self.assertEqual(commit[:3] + commit[4:5], ["git", "commit", "-m", "--"])
        self.assertEqual(sorted(add[4:]), sorted(commit[5:]))
        self.assertEqual(sorted(add[4:]), sorted(
            ["3d_models/PKG0005A.stp", "lib_sym/lib_ics_general.kicad_sym"] +
            ["lib_fp/lib_ics_general.pretty/PKG0005A-%s.kicad_mod" % v for v in ("IPC_A", "IPC_B", "MFG")]))

    def test_a_run_that_writes_nothing_commits_nothing(self):
        self.write_config(git_commit=True)
        code, git = self.run_main("--init-libraries")  # every library exists already
        self.assertEqual((code, git), (0, []))
        self.assertIn("Nothing to commit", self.out)

    def write_config(self, **settings):
        (self.lib / "kicad-part-importer.json").write_text(json.dumps(settings), encoding="utf-8")

    def make_tables(self):
        project = self.lib.parent
        for name, head in (("sym-lib-table", "sym_lib_table"), ("fp-lib-table", "fp_lib_table")):
            (project / name).write_text("(%s\n  (version 7)\n)\n" % head, encoding="utf-8")
        return project

    def test_add_to_project_never_commits_the_project_tables(self):
        project = self.make_tables()
        code, git = self.run_main("--add-to-project", "--commit", "--push", inputs=["5"])
        self.assertEqual((code, git), (0, []))
        self.assertIn("do not apply to --add-to-project", self.err)
        self.assertIn("lib_power_management", (project / "sym-lib-table").read_text(encoding="utf-8"))
        # git_commit / git_push in the config file do not apply either
        self.write_config(git_commit=True, git_push=True)
        code, git = self.run_main("--add-to-project", inputs=["1"])
        self.assertEqual((code, git), (0, []))

    def test_import_with_add_to_project_commits_only_library_files(self):
        self.make_tables()
        code, git = self.run_main(self.zip, "--category", "ics_general", "--add-to-project", "--commit",
                                  inputs=["5", "n"])
        self.assertEqual(code, 0, self.out + self.err)
        self.assertEqual([c[1] for c in git], ["add", "commit"])
        self.assertFalse([p for p in git[0] if "lib-table" in p])
        self.assertIn("Not committed (project files", self.out)


class InitCommitsOnlyWithTheFlag(GitCallsBase):
    """--init commits or pushes only with --commit / --push on its command line:
    git_commit / git_push from a template or the environment would commit (or,
    in a new folder, fail to) the moment the library is created."""

    def template(self, **settings):
        path = Path(self.tmp.name) / "template.json"
        path.write_text(json.dumps(settings), encoding="utf-8")
        return path

    def test_template_git_settings_do_not_commit_at_init(self):
        tpl = self.template(git_commit=True, git_push=True, git_message_prefix="parts: ")
        new = Path(self.tmp.name) / "new_lib"
        code, git = self.run_main("--init", "--library", new, "--config", tpl, "--config-format", "json")
        self.assertEqual((code, git), (0, []), self.out + self.err)
        written = json.loads((new / "kicad-part-importer.json").read_text(encoding="utf-8"))
        self.assertEqual((written["git_commit"], written["git_push"]), (True, True))  # still in the new file

    def test_environment_does_not_commit_at_init(self):
        new = Path(self.tmp.name) / "env_lib"
        code, git = self.run_main("--init", "--library", new, env_extra={"KICAD_PART_IMPORTER_GIT_COMMIT": "1",
                                                                        "KICAD_PART_IMPORTER_GIT_PUSH": "1"})
        self.assertEqual((code, git), (0, []), self.out + self.err)

    def test_commit_flag_commits_the_files_init_wrote(self):
        new = Path(self.tmp.name) / "flag_lib"
        code, git = self.run_main("--init", "--library", new, "--config-format", "json", "--commit")
        self.assertEqual(code, 0, self.out + self.err)
        self.assertEqual([c[1] for c in git], ["add", "commit"])
        self.assertEqual(git[1][:4], ["git", "commit", "-m", "Initialize the part library"])
        paths = git[0][3:]
        self.assertIn("kicad-part-importer.json", paths)
        self.assertEqual(len([p for p in paths if p.startswith("lib_sym/")]), 13)


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


@unittest.skipUnless(shutil.which("git"), "git not found")
class RealGitInAProject(unittest.TestCase):
    """The library inside a project's repository (the layout getting-started.md
    uses): the tool's commit holds only the library files the command wrote,
    never the user's own staged or unstaged work."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.project = t / "board"
        self.lib = H.make_library(self.project / "lib")
        (self.project / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
        self.zip = t / "p.zip"
        H.ti_zip(self.zip)
        H.git(self.project, "init", "-q")
        H.git(self.project, "add", ".")
        H.git(self.project, "commit", "-q", "-m", "board with its library")

    def tearDown(self):
        self.tmp.cleanup()

    def head(self):
        return H.git(self.project, "rev-parse", "HEAD").strip()

    def test_commit_leaves_the_users_staged_board_alone(self):
        (self.project / "board.kicad_pcb").write_text("(kicad_pcb (work in progress))\n", encoding="utf-8")
        H.git(self.project, "add", "board.kicad_pcb")
        r = H.run_importer("--library", self.lib, self.zip, "--commit", stdin="4\nn\n", env_extra=H.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        committed = H.git(self.project, "show", "--name-only", "--format=", "HEAD").split()
        self.assertNotIn("board.kicad_pcb", committed)
        self.assertIn("lib/lib_sym/lib_ics_general.kicad_sym", committed)
        self.assertEqual(H.git(self.project, "diff", "--cached", "--name-only").split(), ["board.kicad_pcb"])

    def test_noop_init_does_not_commit_the_users_edit(self):
        cfg = self.lib / "kicad-part-importer.json"
        cfg.write_text(json.dumps({"git_commit": True}), encoding="utf-8")
        H.git(self.project, "add", ".")
        H.git(self.project, "commit", "-q", "-m", "config")
        cfg.write_text(json.dumps({"git_commit": True, "git_message_prefix": "parts: "}), encoding="utf-8")
        head = self.head()
        r = H.run_importer("--init", "--library", self.lib, env_extra=H.GIT_ENV, stdin="")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.head(), head)
        self.assertEqual(H.git(self.project, "status", "--porcelain").split(), ["M", "lib/kicad-part-importer.json"])

    def test_add_to_project_commit_leaves_the_tables_to_the_user(self):
        for name, head in (("sym-lib-table", "sym_lib_table"), ("fp-lib-table", "fp_lib_table")):
            (self.project / name).write_text("(%s\n  (version 7)\n)\n" % head, encoding="utf-8")
        H.git(self.project, "add", ".")
        H.git(self.project, "commit", "-q", "-m", "tables")
        head = self.head()
        r = H.run_importer("--library", self.lib, "--add-to-project", "--commit", stdin="5\n",
                           env_extra=H.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Error committing", r.stdout + r.stderr)
        self.assertEqual(self.head(), head)
        self.assertEqual(sorted(H.git(self.project, "status", "--porcelain").split()),
                         sorted(["M", "M", "fp-lib-table", "sym-lib-table"]))


@unittest.skipUnless(shutil.which("git"), "git not found")
class RealGitIgnore(unittest.TestCase):
    """A file the command wrote that git ignores (here the model folder, in the
    project's .gitignore) is left out of the commit and named; the other files
    are committed. `git add` of an ignored path fails, and the commit with it."""

    FOOTPRINTS = ["lib/lib_fp/lib_ics_general.pretty/PKG0005A-%s.kicad_mod" % v for v in ("IPC_A", "IPC_B", "MFG")]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.project = t / "board"
        self.lib = H.make_library(self.project / "lib")
        (self.project / ".gitignore").write_text("lib/3d_models/\n", encoding="utf-8")
        self.zip = t / "p.zip"
        H.ti_zip(self.zip)
        H.git(self.project, "init", "-q")
        H.git(self.project, "add", ".")
        H.git(self.project, "commit", "-q", "-m", "board with its library")

    def tearDown(self):
        self.tmp.cleanup()

    def committed(self):
        return sorted(H.git(self.project, "show", "--name-only", "--format=", "HEAD").split())

    def assert_committed_all_but_the_model(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Error committing", r.stdout + r.stderr)
        self.assertIn("Not committed (git ignores them): 3d_models/PKG0005A.stp", r.stdout + r.stderr)
        self.assertEqual(self.committed(), sorted(["lib/lib_sym/lib_ics_general.kicad_sym"] + self.FOOTPRINTS))
        self.assertTrue((self.lib / "3d_models" / "PKG0005A.stp").is_file())
        self.assertEqual(H.git(self.project, "status", "--porcelain"), "")  # nothing left staged or changed

    def test_prompting_import(self):
        r = H.run_importer("--library", self.lib, self.zip, "--commit", stdin="4\nn\n", env_extra=H.GIT_ENV)
        self.assert_committed_all_but_the_model(r)

    def test_planned_import_says_so_in_the_report(self):
        r = H.run_importer("--library", self.lib, self.zip, "--category", "ics_general", "--yes", "--json",
                           "--commit", env_extra=H.GIT_ENV)
        self.assert_committed_all_but_the_model(r)
        rep = json.loads(r.stdout)
        self.assertTrue(rep["ok"], rep)
        self.assertIn("not committed, git ignores them: 3d_models/PKG0005A.stp", rep["warnings"])
        self.assertIn("3d_models/PKG0005A.stp", rep["written"])  # written all the same

    def test_tracked_model_under_an_ignored_folder_is_committed(self):
        # A model committed before its folder went into .gitignore is still tracked: check-ignore does not list
        # it, so it stays in the commit, and a plain `git add` of it would fail.
        model = self.lib / "3d_models" / "PKG0005A.stp"
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_bytes(b"an older model\n")
        H.git(self.project, "add", "-f", "--", "lib/3d_models/PKG0005A.stp")
        H.git(self.project, "commit", "-q", "-m", "model committed before the ignore rule")
        r = H.run_importer("--library", self.lib, self.zip, "--category", "ics_general", "--yes", "--overwrite",
                           "--commit", env_extra=H.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Error committing", r.stdout + r.stderr)
        self.assertIn("lib/3d_models/PKG0005A.stp", self.committed())
        self.assertEqual(model.read_bytes(), H.FAKE_STEP)
        self.assertEqual(H.git(self.project, "status", "--porcelain"), "")

    def test_only_ignored_files_written_commits_nothing(self):
        z = Path(self.tmp.name) / "model_only.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("ONLY.stp", H.FAKE_STEP)
        head = H.git(self.project, "rev-parse", "HEAD")
        r = H.run_importer("--library", self.lib, z, "--category", "ics_general", "--yes", "--commit",
                           env_extra=H.GIT_ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Nothing to commit: git ignores every library file this run changed", r.stdout)
        self.assertEqual(H.git(self.project, "rev-parse", "HEAD"), head)
        self.assertTrue((self.lib / "3d_models" / "ONLY.stp").is_file())


if __name__ == "__main__":
    unittest.main()
