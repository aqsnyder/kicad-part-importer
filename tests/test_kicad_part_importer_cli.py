"""End-to-end tests of kicad_part_importer.py as a command (subprocess), on
scratch libraries made per test. No KiCad needed; see test_kicad_verify.py for
that. Run from the repository root:  python -m unittest discover -s tests -v
"""
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.lib = H.make_library(t / "partlib")
        self.zips = t / "zips"
        self.zips.mkdir()
        # The default model path prefix for this library: ${KIPRJMOD}/partlib/3d_models
        self.prefix = libcfg.LibraryConfig(self.lib).model_prefix

    def tearDown(self):
        self.tmp.cleanup()

    def sym(self, cat):
        return lib3d.read_text(self.lib / "lib_sym" / ("lib_%s.kicad_sym" % cat))

    def fp(self, cat, name):
        return lib3d.read_text(self.lib / "lib_fp" / ("lib_%s.pretty" % cat) / (name + ".kicad_mod"))


class PromptingImport(Base):
    """A bare `kicad-part-importer part.zip` prompts for the library and for the zip."""

    def test_prompts_and_result(self):
        self.assertEqual(self.prefix, "${KIPRJMOD}/partlib/3d_models")
        z = self.zips / "part.zip"
        names = H.ti_zip(z)
        r = H.run_importer("--library-root", self.lib, z, stdin="4\nn\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Enter your choice (0-13)", r.stdout)
        self.assertIn("Delete the zip file? (y/n)", r.stdout)
        self.assertIn("Successfully processed 5/5 files", r.stdout)
        self.assertIn('(symbol "TESTSW1"', self.sym("ics_general"))
        for n in names:  # copied verbatim: no model line added on this path
            self.assertEqual(lib3d.model_refs(self.fp("ics_general", n)), [])
        self.assertTrue((self.lib / "3d_models" / "PKG0005A.stp").exists())
        self.assertTrue(z.exists())

    def test_symbol_library_keeps_lf(self):
        # Appending a symbol must not rewrite the whole library with CRLF on Windows.
        lib = self.lib / "lib_sym" / "lib_ics_general.kicad_sym"
        lib3d.write_text(lib, H.SYMBOL.format(name="EXISTING", fp="x:y"))
        H.ti_zip(self.zips / "part.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "part.zip", stdin="4\nn\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        raw = lib.read_bytes()
        self.assertNotIn(b"\r\n", raw)
        self.assertIn(b'(symbol "EXISTING"', raw)
        self.assertIn(b'(symbol "TESTSW1"', raw)

    def test_cp1252_console_does_not_crash_mid_import(self):
        # The check marks cannot be encoded in cp1252; the import must still finish.
        H.ti_zip(self.zips / "part.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "part.zip", stdin="4\nn\n",
                           env_extra={"PYTHONIOENCODING": "cp1252"}, isolated=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertTrue((self.lib / "lib_fp" / "lib_ics_general.pretty" / "PKG0005A-MFG.kicad_mod").exists())

    def test_library_root_defaults_to_the_current_directory(self):
        H.ti_zip(self.zips / "part.zip")
        r = H.run_importer(self.zips / "part.zip", stdin="4\nn\n", cwd=self.lib)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(symbol "TESTSW1"', self.sym("ics_general"))


class NonInteractiveImport(Base):
    def test_yes_needs_category(self):
        H.ti_zip(self.zips / "p.zip")
        before = H.snapshot(self.lib)
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--yes")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--category is required", r.stdout + r.stderr)
        self.assertEqual(H.snapshot(self.lib), before)

    def test_unknown_category(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--yes", "--category", "nope")
        self.assertEqual(r.returncode, 2)

    def test_dry_run_json_writes_nothing(self):
        names = H.ti_zip(self.zips / "p.zip")
        before = H.snapshot(self.lib)
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)  # stdout holds only the JSON
        self.assertEqual(H.snapshot(self.lib), before)
        self.assertTrue(rep["ok"])
        self.assertEqual(rep["written"], [])
        self.assertEqual([s["name"] for s in rep["symbols"]], ["TESTSW1"])
        self.assertEqual([f["name"] for f in rep["footprints"]], names)
        for f in rep["footprints"]:
            self.assertEqual(f["action"], "add")
            self.assertEqual(f["model"]["action"], "insert")
            self.assertEqual(f["model"]["after"], [self.prefix + "/PKG0005A.stp"])
            self.assertNotIn("_text", f)
        self.assertEqual(rep["models"][0]["action"], "add")
        self.assertTrue(any("declares the name" in w for w in rep["warnings"]))
        self.assertTrue(any("no library prefix" in w for w in rep["warnings"]))

    def test_yes_link_3d_imports_and_links(self):
        names = H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "5",
                           "--link-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["category"], "power_management")
        self.assertEqual(rep["zip_action"], "kept")
        self.assertTrue((self.zips / "p.zip").exists())
        for n in names:
            text = self.fp("power_management", n)
            self.assertEqual(lib3d.model_refs(text), [self.prefix + "/PKG0005A.stp"])
            self.assertNotIn("\n", text.replace("\r\n", ""))  # vendor CRLF kept
        self.assertEqual((self.lib / "3d_models" / "PKG0005A.stp").read_bytes(), H.FAKE_STEP)
        self.assertIn('(symbol "TESTSW1"', self.sym("power_management"))
        self.assertEqual(sorted(rep["written"]), sorted(
            ["3d_models/PKG0005A.stp", "lib_sym/lib_power_management.kicad_sym"] +
            ["lib_fp/lib_power_management.pretty/%s.kicad_mod" % n for n in names]))

    def test_samacsys_bare_model_is_rewritten(self):
        H.samacsys_zip(self.zips / "LIB_TESTTVS.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "LIB_TESTTVS.zip", "--category",
                           "lib_protection", "--link-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["footprints"][0]["model"]["rule"], "named by footprint")
        self.assertEqual(lib3d.model_refs(self.fp("protection", "DIONTEST")), [self.prefix + "/TESTTVS.stp"])
        self.assertIn("license.txt", rep["ignored_files"])
        self.assertTrue((self.lib / "3d_models" / "TESTTVS.stp").exists())
        self.assertFalse(any(p.suffix in (".lib", ".SchLib", ".txt") for p in (self.lib / "3d_models").iterdir()))

    def test_second_import_is_refused_and_writes_nothing(self):
        H.ti_zip(self.zips / "p.zip")
        args = ("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general", "--link-3d", "--yes")
        self.assertEqual(H.run_importer(*args).returncode, 0)
        before = H.snapshot(self.lib)
        r = H.run_importer(*args, "--json")
        self.assertEqual(r.returncode, 3)
        rep = json.loads(r.stdout)
        self.assertIn("symbol TESTSW1 already exists in lib_ics_general (remove or rename it first)", rep["errors"])
        self.assertEqual(H.snapshot(self.lib), before)
        self.assertEqual(self.sym("ics_general").count('(symbol "TESTSW1"'), 1)

    def test_model_conflict_refused_then_overwrite(self):
        (self.lib / "3d_models" / "PKG0005A.stp").write_bytes(b"different")
        H.ti_zip(self.zips / "p.zip")
        base = ("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general", "--yes", "--json")
        before = H.snapshot(self.lib)
        r = H.run_importer(*base)
        self.assertEqual(r.returncode, 3)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["models"][0]["action"], "refused")
        self.assertIn("3d_models/PKG0005A.stp exists with different content (use --overwrite to replace)",
                      rep["errors"])
        self.assertEqual(H.snapshot(self.lib), before)
        r = H.run_importer(*base, "--overwrite")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.lib / "3d_models" / "PKG0005A.stp").read_bytes(), H.FAKE_STEP)

    def test_identical_model_is_reused(self):
        (self.lib / "3d_models" / "PKG0005A.stp").write_bytes(H.FAKE_STEP)
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["models"][0]["action"], "identical")
        self.assertNotIn("3d_models/PKG0005A.stp", rep["written"])

    def test_delete_zip(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--yes", "--delete-zip")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.zips / "p.zip").exists())

    def test_verify_without_kicad_is_a_usage_error_before_any_write(self):
        H.ti_zip(self.zips / "p.zip")
        before = H.snapshot(self.lib)
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--verify-3d", "--kicad-bin", self.zips, "--yes")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no kicad-cli", r.stdout + r.stderr)
        self.assertEqual(H.snapshot(self.lib), before)

    def test_zip_with_two_footprints_of_one_name_is_refused(self):
        z = self.zips / "two.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a/X.kicad_mod", H.FP_UL.format(declared="X"))
            zf.writestr("b/X.kicad_mod", H.FP_UL.format(declared="X") + "\n")
        r = H.run_importer("--library-root", self.lib, z, "--category", "ics_general", "--yes", "--json")
        self.assertEqual(r.returncode, 3)
        self.assertIn("the zip holds two footprint files named x.kicad_mod", json.loads(r.stdout)["errors"])

    def test_prompting_commands_rejected_without_prompts(self):
        r = H.run_importer("--library-root", self.lib, "--migrate", "--yes")
        self.assertEqual(r.returncode, 2)

    def test_snapeda_zip_without_model(self):
        z = self.zips / "TESTREG1_7.zip"
        H.snapeda_zip(z)
        digest = hashlib.sha256(z.read_bytes()).hexdigest()
        r = H.run_importer("--library-root", self.lib, z, "--category", "power_management", "--link-3d",
                           "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual([s["name"] for s in rep["symbols"]], ["TESTREG1-7"])
        self.assertEqual(rep["footprints"][0]["model"]["rule"], "no model offered")
        self.assertTrue(any("no 3D model" in w for w in rep["warnings"]))
        self.assertTrue(any("names library 'TESTREG1-7'" in w for w in rep["warnings"]))
        self.assertEqual(sorted(rep["ignored_files"]), ["License.txt", "how-to-import.htm"])
        self.assertEqual(hashlib.sha256(z.read_bytes()).hexdigest(), digest)  # the zip is left alone


class Check3D(Base):
    def setUp(self):
        super().setUp()
        pretty = self.lib / "lib_fp" / "lib_protection.pretty"
        (self.lib / "3d_models" / "TVS24A.stp").write_bytes(H.FAKE_STEP)
        lib3d.write_text(pretty / "TVS24A.kicad_mod", H.FP_SAMACSYS.format(name="TVS24A", model="TVS24A.stp"))

    def test_check_fix_cycle(self):
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["counts"], {"bare": 1})
        before = H.snapshot(self.lib)
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--fix-3d", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["changed"], ["lib_fp/lib_protection.pretty/TVS24A.kicad_mod"])
        self.assertEqual(H.snapshot(self.lib), before)
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--fix-3d", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["counts"], {"ok": 1})
        self.assertEqual(lib3d.model_refs(self.fp("protection", "TVS24A")), [self.prefix + "/TVS24A.stp"])

    def test_fix_3d_without_check_3d_is_a_usage_error(self):
        # Without --check-3d these options would be ignored and a zip would go to the prompting import.
        H.ti_zip(self.zips / "p.zip")
        before = H.snapshot(self.lib)
        for extra in (("--fix-3d",), ("--all-footprint-libs",), (self.zips / "p.zip", "--fix-3d")):
            r = H.run_importer("--library-root", self.lib, *extra, stdin="4\nn\n")
            self.assertEqual(r.returncode, 2, (extra, r.stdout, r.stderr))
            self.assertIn("need --check-3d", r.stderr)
            self.assertNotIn("Enter your choice", r.stdout)
        self.assertEqual(H.snapshot(self.lib), before)


if __name__ == "__main__":
    unittest.main()
