"""The command-line contract scripts and agents rely on:

- with --json, stdout holds exactly one JSON object, usage errors included;
- a prompt that gets no answer (stdin closed) stops with exit code 2 and a
  hint, never with a traceback;
- exit codes: 0 ok, 1 a requested action failed, 2 usage (including a missing
  input file), 3 refused.
"""
import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg
import kicad_part_importer as kpi


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.lib = H.make_library(self.t / "partlib")
        self.zip = self.t / "p.zip"
        H.ti_zip(self.zip)

    def tearDown(self):
        self.tmp.cleanup()

    def run_lib(self, *args, **kw):
        kw.setdefault("stdin", "")  # a closed stdin unless the test answers the prompts
        return H.run_importer("--library", self.lib, *args, **kw)

    def one_json_object(self, r):
        """stdout is one JSON object and nothing else."""
        try:
            return json.loads(r.stdout)
        except ValueError:
            self.fail("stdout is not one JSON object:\n%r\nstderr:\n%s" % (r.stdout, r.stderr))


class JsonOnUsageErrors(Base):
    """--json prints exactly one JSON object on stdout for usage and config errors too (exit 2)."""

    def assert_usage_json(self, *args, error=None):
        r = self.run_lib(*args)
        self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
        rep = self.one_json_object(r)
        self.assertEqual((rep["exit_code"], rep["ok"]), (2, False), args)
        self.assertTrue(rep["errors"], args)
        if error:
            self.assertTrue(any(error in e for e in rep["errors"]), (error, rep["errors"]))
        self.assertNotIn("Traceback", r.stderr)
        return rep

    def test_no_zip(self):
        self.assert_usage_json("--json", "--category", "1", error="need a .zip file")

    def test_missing_zip(self):
        self.assert_usage_json(self.t / "missing.zip", "--json", "--category", "1", error="not found")

    def test_keep_zip_and_delete_zip(self):
        self.assert_usage_json(self.zip, "--json", "--category", "1", "--keep-zip", "--delete-zip",
                               error="--keep-zip and --delete-zip")

    def test_prompting_command_with_json(self):
        self.assert_usage_json(self.zip, "--json", "--category", "1", "--migrate", error="asks questions")

    def test_bad_setting(self):
        self.assert_usage_json(self.zip, "--json", "--category", "1", "--library-mount", "bad",
                               error="library_mount")

    def test_fix_3d_without_check_3d(self):
        self.assert_usage_json("--json", "--fix-3d", error="need --check-3d")

    def test_init_with_json(self):
        self.assert_usage_json("--init", "--json", error="--init runs alone")

    def test_unknown_option(self):
        rep = self.assert_usage_json("--check-3d", "--json", "--no-such-option")
        self.assertIn("--no-such-option", rep["errors"][0])

    def test_nothing_written(self):
        before = H.snapshot(self.lib)
        self.assert_usage_json(self.zip, "--json", "--category", "1", "--keep-zip", "--delete-zip")
        self.assertEqual(H.snapshot(self.lib), before)


class ClosedStdin(Base):
    """A prompt with no answer (stdin closed) stops cleanly: exit 2, a hint, no traceback."""

    def assert_stopped(self, r, hint):
        self.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertNotIn("EOFError", r.stdout + r.stderr)
        self.assertIn("stdin closed", r.stdout + r.stderr)
        self.assertIn(hint, r.stdout + r.stderr)

    def test_planned_import_menu(self):
        before = H.snapshot(self.lib)
        r = self.run_lib(self.zip, "--link-3d")
        self.assert_stopped(r, "--category")
        self.assertEqual(H.snapshot(self.lib), before)

    def test_interactive_import_menu(self):
        before = H.snapshot(self.lib)
        r = self.run_lib(self.zip)
        self.assert_stopped(r, "--category")
        self.assertEqual(H.snapshot(self.lib), before)

    def test_add_to_project_menu(self):
        for name, head in (("sym-lib-table", "sym_lib_table"), ("fp-lib-table", "fp_lib_table")):
            (self.t / name).write_text("(%s\n  (version 7)\n)\n" % head, encoding="utf-8")
        before = H.snapshot(self.t)
        r = self.run_lib("--add-to-project")
        self.assert_stopped(r, "--add-to-project asks")
        self.assertEqual(H.snapshot(self.t), before)

    def test_migrate_menu(self):
        old = H.write_eol(self.t / "old.kicad_sym", H.old_symbol_library(("OLDREG", "x:y")))
        before = H.snapshot(self.lib)
        r = self.run_lib("--migrate", old)
        self.assert_stopped(r, "run it in a terminal")
        self.assertEqual(H.snapshot(self.lib), before)

    def test_delete_question_keeps_the_zip(self):
        # The import itself was answered; no answer to "delete the zip?" keeps it.
        r = self.run_lib(self.zip, stdin="4\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertIn("No answer (stdin closed): kept p.zip", r.stdout)
        self.assertTrue(self.zip.exists())
        self.assertIn('(symbol "TESTSW1"', lib3d.read_text(self.lib / "lib_sym" / "lib_ics_general.kicad_sym"))


class ExitCodes(Base):
    def test_missing_input_file_is_a_usage_error_everywhere(self):
        for args in ((self.t / "missing.zip",),
                     (self.t / "missing.zip", "--category", "1", "--yes"),
                     ("--migrate", self.t / "missing.kicad_sym"),
                     (self.t / "missing.kicad_sym",),
                     ("--migrate-schematic", self.t / "missing.kicad_sch")):
            r = self.run_lib(*args)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
            self.assertIn("not found", r.stderr, args)

    def test_unsupported_file_and_nothing_to_do_are_usage_errors(self):
        notes = self.t / "notes.txt"
        notes.write_text("x", encoding="utf-8")
        self.assertEqual(self.run_lib(notes).returncode, 2)
        r = self.run_lib()
        self.assertEqual(r.returncode, 2)
        self.assertIn("nothing to do", r.stderr)

    def test_unreadable_zip_is_a_usage_error_everywhere(self):
        # Not a zip at all, and a zip whose model fails its CRC check (one byte
        # changed): exit 2 on the prompting and the planned path alike.
        bad = self.t / "bad.zip"
        bad.write_bytes(b"not a zip")
        crc = self.t / "crc.zip"
        raw = bytearray(self.zip.read_bytes())
        raw[raw.index(b"END-ISO-10303-21;")] ^= 0x20  # 'E' -> 'e' in the stored model
        crc.write_bytes(bytes(raw))
        before = H.snapshot(self.lib)
        for z in (bad, crc):
            for args in ((z,), (z, "--category", "1", "--yes"), (z, "--category", "1", "--dry-run", "--json")):
                r = self.run_lib(*args)
                where = (z.name, args[1:], r.stdout, r.stderr)
                self.assertEqual(r.returncode, 2, where)
                self.assertIn("cannot read zip", r.stdout + r.stderr, where)
                self.assertNotIn("Traceback", r.stdout + r.stderr, where)
                if "--json" in args:
                    rep = self.one_json_object(r)
                    self.assertEqual((rep["exit_code"], rep["ok"]), (2, False))
                    self.assertTrue(any("cannot read zip" in e for e in rep["errors"]), rep["errors"])
        self.assertEqual(H.snapshot(self.lib), before)
        self.assertEqual(bad.read_bytes(), b"not a zip")  # the input is left alone

    def test_add_to_project_without_tables_fails(self):
        r = self.run_lib("--add-to-project")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("Project library tables not found", r.stdout)

    def test_interactive_import_of_a_zip_without_kicad_files_fails(self):
        z = self.t / "empty.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("readme.txt", "nothing here\n")
        r = self.run_lib(z, stdin="1\nn\n")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)


class FailedGitExits1(unittest.TestCase):
    """A requested commit or push that fails makes the run fail (exit 1), and the
    planned import says so in its JSON report. git is a recorder here that fails
    the command named by fail_on."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.lib = H.make_library(t / "partlib")
        self.zip = t / "p.zip"
        H.ti_zip(self.zip)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args, fail_on="commit", inputs=()):
        def fake_run(cmd, *a, **kw):
            rc = 1 if cmd[:2] == ["git", fail_on] else 0
            return subprocess.CompletedProcess(cmd, rc, "", "fatal: recorder says no\n" if rc else "")

        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, H.clean_env(), clear=True), \
                mock.patch.object(kpi.subprocess, "run", side_effect=fake_run), \
                mock.patch("builtins.input", side_effect=list(inputs)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                kpi.main(["--library", str(self.lib)] + [str(a) for a in args])
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_planned_import_commit_failure(self):
        code, out, err = self.run_main(self.zip, "--category", "ics_general", "--yes", "--json", "--commit")
        self.assertEqual(code, 1, err)
        rep = json.loads(out)
        self.assertEqual((rep["exit_code"], rep["ok"]), (1, False))
        self.assertTrue(any("commit failed" in e for e in rep["errors"]), rep["errors"])
        self.assertTrue(rep["written"])  # the files are written all the same

    def test_planned_import_push_failure(self):
        code, out, err = self.run_main(self.zip, "--category", "ics_general", "--yes", "--json", "--commit",
                                       "--push", fail_on="push")
        self.assertEqual(code, 1, err)
        self.assertTrue(any("push failed" in e for e in json.loads(out)["errors"]))

    def test_prompting_commands_commit_failure(self):
        code, out, err = self.run_main(self.zip, "--commit", inputs=["4", "n"])
        self.assertEqual(code, 1, out + err)
        (self.lib / "lib_sym" / "lib_sensors.kicad_sym").unlink()
        code, out, err = self.run_main("--init-libraries", "--commit")
        self.assertEqual(code, 1, out + err)


class LoadErrorsFailTheCheck(unittest.TestCase):
    """--verify-3d: a footprint KiCad cannot load at all is a failure, and is named.
    KiCad is replaced by a canned report here; test_kicad_verify.py has the real run."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = H.make_library(Path(self.tmp.name) / "partlib")
        mount = libcfg.LibraryConfig(self.lib).library_mount
        (self.lib / "3d_models" / "A.stp").write_bytes(H.FAKE_STEP)
        pretty = self.lib / "lib_fp" / "lib_protection.pretty"
        for name in ("GOOD", "BROKEN"):
            lib3d.write_text(pretty / (name + ".kicad_mod"),
                             H.FP_SAMACSYS.format(name=name, model='"%s/3d_models/A.stp"' % mount))
        self.good, self.broken = str(pretty / "GOOD.kicad_mod"), str(pretty / "BROKEN.kicad_mod")

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *args):
        report = {"kicad_version": "10.0.7", "kicad_cli_exit": 0, "checked": 2, "loaded": [self.good],
                  "failed": [], "no_body": [], "no_model": [],
                  "load_errors": [{"footprint": self.broken, "error": "FootprintLoad returned None"}], "log": []}
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, H.clean_env(), clear=True), \
                mock.patch.object(kpi.lib3d, "find_kicad", return_value=("kicad-cli", "python")), \
                mock.patch.object(kpi.LibraryManager, "_verify", return_value=report), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                kpi.main(["--library", str(self.lib)] + [str(a) for a in args])
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_check_3d_fails_and_names_the_footprint(self):
        code, out, err = self.run_main("--check-3d", "--verify-3d", "--json")
        self.assertEqual(code, 1, err)
        rep = json.loads(out)
        self.assertEqual((rep["exit_code"], rep["ok"]), (1, False))
        self.assertEqual(rep["counts"], {"ok": 2})  # the paths themselves are fine
        self.assertIn("✗ KiCad could not load BROKEN.kicad_mod: FootprintLoad returned None", err)
        self.assertIn("1 that KiCad could not load", err)

    def test_import_names_the_footprint(self):
        zpath = Path(self.tmp.name) / "p.zip"
        H.ti_zip(zpath)
        code, out, err = self.run_main(zpath, "--category", "ics_general", "--link-3d", "--verify-3d",
                                       "--dry-run")
        self.assertEqual(code, 1, out + err)
        self.assertIn("✗ KiCad could not load BROKEN.kicad_mod: FootprintLoad returned None", out)


if __name__ == "__main__":
    unittest.main()
