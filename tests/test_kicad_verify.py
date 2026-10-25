"""Integration tests that run KiCad (kicad-cli + KiCad's Python with pcbnew).
Skipped when KiCad is not found (set KICAD_BIN to its bin folder to point at it).
The model file is a STEP body that kicad-cli exports from a tiny generated
board, used inside synthetic vendor zips.
"""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg

try:
    KICAD_CLI = lib3d.find_kicad()[0]
except RuntimeError:
    KICAD_CLI = None


@unittest.skipUnless(KICAD_CLI, "KiCad not found")
class KiCadVerify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._step_dir = tempfile.TemporaryDirectory(prefix="kpi_step_")
        cls.step = H.make_step_with_kicad(KICAD_CLI, Path(cls._step_dir.name) / "BOX.step")

    @classmethod
    def tearDownClass(cls):
        cls._step_dir.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.lib = H.make_library(t / "partlib")
        self.zips = t / "zips"
        self.zips.mkdir()
        self.mount = libcfg.LibraryConfig(self.lib).library_mount

    def tearDown(self):
        self.tmp.cleanup()

    def test_linked_footprints_load(self):
        H.ti_zip(self.zips / "p.zip", step=self.step)
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        v = json.loads(r.stdout)["verify_3d"]
        self.assertEqual((len(v["loaded"]), v["failed"], v["load_errors"]), (3, [], []))

    def test_dry_run_verifies_without_writing(self):
        H.ti_zip(self.zips / "p.zip", step=self.step)
        before = H.snapshot(self.lib)
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--verify-3d", "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(json.loads(r.stdout)["verify_3d"]["loaded"]), 3)
        self.assertEqual(H.snapshot(self.lib), before)

    def test_bare_samacsys_name_fails_until_linked(self):
        H.samacsys_zip(self.zips / "s.zip", step=self.step)
        # Imported as-is (no --link-3d): KiCad cannot find the bare file name.
        r = H.run_importer("--library-root", self.lib, self.zips / "s.zip", "--category", "protection",
                           "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        v = json.loads(r.stdout)["verify_3d"]
        self.assertEqual(len(v["failed"]), 1)
        self.assertIn("File not found: TESTTVS.stp", v["failed"][0]["reason"])
        # The library check sees it, fixes it, and KiCad then loads it.
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--fix-3d", "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["changed"], ["lib_fp/lib_protection.pretty/DIONTEST.kicad_mod"])
        self.assertEqual((len(rep["verify_3d"]["loaded"]), rep["verify_3d"]["failed"]), (1, []))

    def test_unreadable_model_is_reported(self):
        H.ti_zip(self.zips / "p.zip", step=b"not a step file\n")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        v = json.loads(r.stdout)["verify_3d"]
        self.assertEqual(len(v["failed"]), 3)
        self.assertTrue(all("not a readable model file" in f["reason"] for f in v["failed"]))
        self.assertEqual(len(v["no_body"]), 3)

    def test_delete_zip_kept_when_a_model_does_not_load(self):
        H.ti_zip(self.zips / "p.zip", step=b"not a step file\n")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "ics_general",
                           "--link-3d", "--verify-3d", "--yes", "--delete-zip", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(json.loads(r.stdout)["zip_action"], "kept")
        self.assertTrue((self.zips / "p.zip").exists())

    def test_symbol_only_zip_has_nothing_to_load(self):
        z = self.zips / "sym.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("X.kicad_sym", H.SYMBOL.format(name="SYMONLY", fp="lib_ics_general:PKG"))
        r = H.run_importer("--library-root", self.lib, z, "--category", "ics_general", "--verify-3d", "--yes",
                           "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["verify_3d"]["checked"], 0)

    def test_dead_extra_reference_next_to_a_loading_one(self):
        # A bare name that does not load, then the library path that does: the
        # part still has its body, and --fix-3d removes the dead block instead
        # of duplicating the good one.
        (self.lib / "3d_models" / "REAL.step").write_bytes(self.step)
        pretty = self.lib / "lib_fp" / "lib_protection.pretty"
        fp = H.FP_SAMACSYS.format(name="TWO", model="REAL.step")
        good = '  (model "%s/3d_models/REAL.step"\n    (at (xyz 0 0 0))\n    (scale (xyz 1 1 1))\n' \
               '    (rotate (xyz 0 0 0))\n  )\n' % self.mount
        lib3d.write_text(pretty / "TWO.kicad_mod", fp[:fp.rstrip().rfind(")")] + good + ")\n")
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--verify-3d", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        v = json.loads(r.stdout)["verify_3d"]
        self.assertEqual([f["body_loaded"] for f in v["failed"]], [True])
        self.assertEqual(v["no_body"], [])
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--fix-3d", "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["verify_3d"]["failed"], [])
        self.assertEqual(lib3d.model_refs(lib3d.read_text(pretty / "TWO.kicad_mod")),
                         [self.mount + "/3d_models/REAL.step"])

    def test_environment_variable_mount(self):
        # A library reached through a path variable of its own, not ${KIPRJMOD}.
        H.ti_zip(self.zips / "p.zip", step=self.step)
        r = H.run_importer("--library-root", self.lib, "--library-mount", "${KPI_TEST_PARTLIB}",
                           self.zips / "p.zip", "--category", "ics_general", "--link-3d", "--verify-3d", "--yes",
                           "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["footprints"][0]["model"]["after"], ["${KPI_TEST_PARTLIB}/3d_models/PKG0005A.stp"])
        v = rep["verify_3d"]
        self.assertEqual((len(v["loaded"]), v["failed"]), (3, []))

    def test_mount_outside_the_project_folder(self):
        # Projects next to the library rather than around it: ${KIPRJMOD}/../<library>.
        H.ti_zip(self.zips / "p.zip", step=self.step)
        project = Path(self.tmp.name) / "projects" / "board1"
        project.mkdir(parents=True)
        r = H.run_importer("--library-root", self.lib, "--project-dir", project, self.zips / "p.zip",
                           "--category", "ics_general", "--link-3d", "--verify-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["footprints"][0]["model"]["after"],
                         ["${KIPRJMOD}/../../partlib/3d_models/PKG0005A.stp"])
        self.assertEqual((len(rep["verify_3d"]["loaded"]), rep["verify_3d"]["failed"]), (3, []))


if __name__ == "__main__":
    unittest.main()
