"""Unit tests for kicad_lib_3d (no KiCad needed). Run from the repository root:
    python -m unittest discover -s tests -v
"""
import os
import tempfile
import unittest

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg

PREFIX = "${KIPRJMOD}/kicad_library/3d_models"

MODERN = """(footprint "PKG6_TEX"
\t(version 20241229)
\t(generator "pcbnew")
\t(layer "F.Cu")
\t(pad "1" smd rect
\t\t(at -0.65 -0.65)
\t\t(size 0.4 0.4)
\t\t(layers "F.Cu" "F.Mask" "F.Paste")
\t)
\t(embedded_fonts no)
\t(model "OLD.stp"
\t\t(offset
\t\t\t(xyz 0.1 0.2 0)
\t\t)
\t\t(scale
\t\t\t(xyz 1 1 1)
\t\t)
\t\t(rotate
\t\t\t(xyz 0 0 90)
\t\t)
\t)
)
"""


def balanced(text):
    depth, in_str, esc = 0, False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


class ModelFiles(unittest.TestCase):
    def test_extensions(self):
        for n in ("a.step", "A.STEP", "b.stp", "c.wrl", "d.stpz"):
            self.assertTrue(lib3d.is_model_file(n), n)

    def test_text_with_3d_in_its_name_is_not_a_model(self):
        # A rule like "'3d' in the name" would copy this vendor readme into the model folder.
        self.assertFalse(lib3d.is_model_file("readme-and-terms-of-use-3d-cad-models.txt"))
        self.assertFalse(lib3d.is_model_file("How_To_Use_Models.pdf"))


class ModelRefs(unittest.TestCase):
    def test_quoted_and_unquoted(self):
        self.assertEqual(lib3d.model_refs(MODERN), ["OLD.stp"])
        legacy = H.FP_SAMACSYS.format(name="X", model="TVS16CA.stp")
        self.assertEqual(lib3d.model_refs(legacy), ["TVS16CA.stp"])
        self.assertEqual(lib3d.model_refs(H.crlf(legacy)), ["TVS16CA.stp"])

    def test_windows_path_with_escaped_backslashes(self):
        t = '(footprint "x"\n  (model "D:\\\\parts\\\\models\\\\X.stp"\n  )\n)\n'
        self.assertEqual(lib3d.model_refs(t), ["D:\\parts\\models\\X.stp"])
        self.assertEqual(lib3d.model_basename(lib3d.model_refs(t)[0]), "X.stp")

    def test_footprint_name(self):
        self.assertEqual(lib3d.footprint_name(MODERN), "PKG6_TEX")
        self.assertEqual(lib3d.footprint_name(H.FP_SAMACSYS.format(name="DIONM", model="a.stp")), "DIONM")
        self.assertEqual(lib3d.footprint_name("\n(footprint \"IC_X\" (layer \"F.Cu\"))"), "IC_X")


class SetModelPath(unittest.TestCase):
    def test_rewrite_keeps_offset_and_rotation(self):
        new, action = lib3d.set_model_path(MODERN, PREFIX + "/PKG0006A.stp")
        self.assertEqual(action, "rewrite")
        self.assertIn('(model "${KIPRJMOD}/kicad_library/3d_models/PKG0006A.stp"', new)
        self.assertIn("(xyz 0.1 0.2 0)", new)
        self.assertIn("(xyz 0 0 90)", new)
        self.assertEqual(new.count("\n"), MODERN.count("\n"))

    def test_rewrite_unquoted_legacy_and_keep_crlf(self):
        legacy = H.crlf(H.FP_SAMACSYS.format(name="X", model="TVS16CA.stp"))
        new, action = lib3d.set_model_path(legacy, PREFIX + "/TVS16CA.stp")
        self.assertEqual(action, "rewrite")
        self.assertEqual(lib3d.model_refs(new), [PREFIX + "/TVS16CA.stp"])
        self.assertEqual(new.count("\r\n"), legacy.count("\r\n"))
        self.assertNotIn("\n", new.replace("\r\n", ""))

    def test_no_change_when_already_there(self):
        once, _ = lib3d.set_model_path(MODERN, PREFIX + "/A.stp")
        twice, action = lib3d.set_model_path(once, PREFIX + "/A.stp")
        self.assertEqual(action, "keep")
        self.assertEqual(once, twice)

    def test_predicate_limits_rewrite(self):
        t = MODERN.replace('\t(model "OLD.stp"', '\t(model "KEEP.wrl"\n\t)\n\t(model "OLD.stp"')
        new, _ = lib3d.set_model_path(t, PREFIX + "/NEW.stp", replace=lambda o: o == "OLD.stp")
        self.assertEqual(lib3d.model_refs(new), ["KEEP.wrl", PREFIX + "/NEW.stp"])

    def test_insert_space_style_crlf(self):
        fp = H.crlf(H.FP_UL.format(declared="PKG-IPC_A"))
        new, action = lib3d.set_model_path(fp, PREFIX + "/PKG.stp")
        self.assertEqual(action, "insert")
        self.assertEqual(lib3d.model_refs(new), [PREFIX + "/PKG.stp"])
        self.assertTrue(balanced(new))
        self.assertTrue(new.rstrip().endswith(")"))
        self.assertNotIn("\n", new.replace("\r\n", ""))  # every line CRLF
        self.assertIn('  (model "%s/PKG.stp"\r\n    (offset (xyz 0 0 0))\r\n' % PREFIX, new)
        self.assertEqual(new.count("\r\n"), fp.count("\r\n") + 5)

    def test_insert_tab_style(self):
        t = MODERN.split("\t(model")[0] + ")\n"
        new, action = lib3d.set_model_path(t, PREFIX + "/X.step")
        self.assertEqual(action, "insert")
        self.assertIn('\n\t(model "%s/X.step"\n\t\t(offset\n\t\t\t(xyz 0 0 0)' % PREFIX, new)
        self.assertTrue(balanced(new))

    def test_model_ref_for(self):
        self.assertEqual(lib3d.model_ref_for("A.stp", PREFIX + "/"), PREFIX + "/A.stp")


class MatchModel(unittest.TestCase):
    def test_named_by_footprint_wins(self):
        self.assertEqual(lib3d.match_model("DIOM5436X261N", ["tvs16ca.STP"], ["TVS16CA.stp", "Other.stp"]),
                         ("TVS16CA.stp", "named by footprint"))

    def test_only_model(self):
        self.assertEqual(lib3d.match_model("SMA_DIO-L", [], ["SMA_DIO.step"])[0], "SMA_DIO.step")

    def test_density_variants(self):
        models = ["PKG0005A.stp", "PKG0006A.stp"]
        for stem in ("PKG0005A-IPC_A", "PKG0005A-IPC_B", "PKG0005A-MFG"):
            self.assertEqual(lib3d.match_model(stem, [], models), ("PKG0005A.stp", "same stem"), stem)
        self.assertEqual(lib3d.match_model("PKG0006A_N", [], models)[0], "PKG0006A.stp")

    def test_stem_prefix(self):
        self.assertEqual(lib3d.match_model("SOT23-5_HAND", [], ["SOT23-5.step", "SOT23.step"]),
                         ("SOT23-5.step", "stem prefix"))

    def test_ambiguous_and_none(self):
        name, rule = lib3d.match_model("QFN", [], ["A.stp", "B.stp"])
        self.assertIsNone(name)
        self.assertTrue(rule.startswith("ambiguous"))
        self.assertEqual(lib3d.match_model("QFN", [], []), (None, "no model offered"))

    def test_variant_base(self):
        self.assertEqual(lib3d.variant_base("PKG0005A-IPC_B"), "PKG0005A")
        self.assertEqual(lib3d.variant_base("SMA_DIO-L"), "SMA_DIO")
        self.assertEqual(lib3d.variant_base("QFN24_2P5XP85X1P45_TEX-M"), "QFN24_2P5XP85X1P45_TEX")
        self.assertEqual(lib3d.variant_base("SOIC-8"), "SOIC-8")


class ClassifyAndFix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = H.make_library(self.tmp.name)
        self.cfg = libcfg.LibraryConfig(self.root)
        (self.root / "3d_models" / "TVS24A.stp").write_bytes(H.FAKE_STEP)
        (self.root / "3d_models" / "Mixed.STEP").write_bytes(H.FAKE_STEP)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kinds(self):
        r = self.root
        mount = self.cfg.library_mount
        self.assertEqual(lib3d.classify_ref(mount + "/3d_models/TVS24A.stp", r), ("ok", "3d_models/TVS24A.stp"))
        self.assertEqual(lib3d.classify_ref(mount + "/3d_models/mixed.step", r), ("case", "3d_models/Mixed.STEP"))
        self.assertEqual(lib3d.classify_ref(mount + "/3d_models/NOPE.stp", r), ("missing", None))
        self.assertEqual(lib3d.classify_ref("${KICAD10_3DMODEL_DIR}/Resistor_SMD.3dshapes/R.step", r),
                         ("stock", None))
        self.assertEqual(lib3d.classify_ref("TVS24A.stp", r), ("bare", "3d_models/TVS24A.stp"))
        self.assertEqual(lib3d.classify_ref("NOPE.stp", r), ("bare", None))
        self.assertEqual(lib3d.classify_ref("D:\\old\\lib\\TVS24A.stp", r), ("absolute", "3d_models/TVS24A.stp"))
        self.assertEqual(lib3d.classify_ref("${KICAD_3D_PROJECT_MODELS}/a/b/TVS24A.stp", r),
                         ("other-var", "3d_models/TVS24A.stp"))

    def test_folder_in_the_wrong_case_is_case_not_ok(self):
        # The folder part of the path counts too: "3D_Models/X" opens "3d_models/X"
        # on Windows and macOS only. (On Linux it used to be "missing", with no fix.)
        mount = self.cfg.library_mount
        self.assertEqual(lib3d.classify_ref(mount + "/3D_Models/TVS24A.stp", self.root),
                         ("case", "3d_models/TVS24A.stp"))
        self.assertEqual(lib3d.classify_ref(mount + "/3D_MODELS/mixed.step", self.root),
                         ("case", "3d_models/Mixed.STEP"))
        self.assertEqual(lib3d.classify_ref(mount + "/3D_Models/NOPE.stp", self.root), ("missing", None))
        self.assertEqual(lib3d.real_path_in(self.root, "3D_models/TVS24A.stp"), "3d_models/TVS24A.stp")
        self.assertIsNone(lib3d.real_path_in(self.root, "3d_models"))  # a folder, not a file

    def test_check_and_fix_a_folder_in_the_wrong_case(self):
        pretty = self.root / "lib_fp" / "lib_protection.pretty"
        bad = self.cfg.library_mount + "/3D_Models/TVS24A.stp"
        lib3d.write_text(pretty / "TVS24A.kicad_mod", H.FP_SAMACSYS.format(name="TVS24A", model='"%s"' % bad))
        rep = lib3d.check_library(self.root)
        self.assertEqual(rep["counts"], {"case": 1})
        self.assertEqual(rep["fixable"][0]["fix"], self.cfg.library_mount + "/3d_models/TVS24A.stp")
        lib3d.apply_fixes(self.root, rep["fixable"])
        self.assertEqual(lib3d.check_library(self.root)["counts"], {"ok": 1})

    def test_found_model_gets_the_folder_spelling_on_disk(self):
        # model_dir "3D_Models" names the folder 3d_models in another case: a model
        # found there is pointed at the folder as it is spelled on disk, which is the
        # one that opens on Linux too (the configured spelling used to be kept, and
        # on Linux the model was not found at all).
        (self.root / "3d_models" / "BARE.step").write_bytes(H.FAKE_STEP)
        cfg = libcfg.LibraryConfig(self.root, model_dir="3D_Models")
        self.assertEqual(lib3d.find_model_in_library("BARE.step", cfg), "3d_models/BARE.step")
        self.assertEqual(lib3d.find_model_in_library("bare.STEP", cfg), "3d_models/BARE.step")
        self.assertEqual(lib3d.classify_ref("BARE.step", cfg), ("bare", "3d_models/BARE.step"))
        pretty = self.root / "lib_fp" / "lib_protection.pretty"
        lib3d.write_text(pretty / "B.kicad_mod", H.FP_SAMACSYS.format(name="B", model="BARE.step"))
        rep = lib3d.check_library(cfg)
        self.assertEqual(rep["counts"], {"bare": 1})
        self.assertEqual(rep["fixable"][0]["fix"], cfg.library_mount + "/3d_models/BARE.step")

    def test_model_search_dirs_are_searched_after_the_model_dir(self):
        d = self.root / "vendor" / "Parts.3dshapes"
        d.mkdir(parents=True)
        (d / "XCVR1029.stp").write_bytes(H.FAKE_STEP)
        (d / "TVS24A.stp").write_bytes(H.FAKE_STEP)
        ref = "D:\\old\\vendor_export\\Parts.3dshapes\\XCVR1029.stp"
        # Not searched unless configured.
        self.assertEqual(lib3d.classify_ref(ref, self.root), ("absolute", None))
        cfg = libcfg.LibraryConfig(self.root, model_search_dirs=["vendor/Parts.3dshapes"])
        self.assertEqual(lib3d.classify_ref(ref, cfg), ("absolute", "vendor/Parts.3dshapes/XCVR1029.stp"))
        self.assertEqual(lib3d.find_model_in_library("TVS24A.stp", cfg), "3d_models/TVS24A.stp")

    def test_check_and_fix(self):
        pretty = self.root / "lib_fp" / "lib_protection.pretty"
        lib3d.write_text(pretty / "TVS24A.kicad_mod", H.crlf(H.FP_SAMACSYS.format(name="TVS24A", model="TVS24A.stp")))
        lib3d.write_text(pretty / "GONE.kicad_mod", H.FP_SAMACSYS.format(name="GONE", model="GONE.stp"))
        lib3d.write_text(pretty / "NOMODEL.kicad_mod", H.FP_UL.format(declared="NOMODEL"))
        rep = lib3d.check_library(self.root)
        self.assertEqual(rep["footprints"], 3)
        self.assertEqual(rep["counts"], {"bare": 2, "none": 1})
        self.assertEqual([r["footprint"] for r in rep["fixable"]], ["lib_fp/lib_protection.pretty/TVS24A.kicad_mod"])
        self.assertEqual([r["ref"] for r in rep["unfixable"]], ["GONE.stp"])

        before = H.snapshot(self.root)
        self.assertEqual(lib3d.apply_fixes(self.root, rep["fixable"], dry_run=True),
                         ["lib_fp/lib_protection.pretty/TVS24A.kicad_mod"])
        self.assertEqual(H.snapshot(self.root), before)

        lib3d.apply_fixes(self.root, rep["fixable"])
        text = lib3d.read_text(pretty / "TVS24A.kicad_mod")
        self.assertEqual(lib3d.model_refs(text), [self.cfg.library_mount + "/3d_models/TVS24A.stp"])
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertEqual(lib3d.check_library(self.root)["counts"], {"ok": 1, "bare": 1, "none": 1})

    def test_dead_duplicate_is_removed_not_rewritten(self):
        # A common form: a bare name KiCad cannot find, then the library path
        # that loads. Rewriting the bare one would give the part two coincident
        # bodies; it has to go instead.
        good = self.cfg.library_mount + "/3d_models/TVS24A.stp"
        dead = MODERN.replace("OLD.stp", "TVS24A.stp")
        both = dead.replace("\t)\n)\n", "\t)\n" + dead[dead.index("\t(model"):].replace(
            '"TVS24A.stp"', '"%s"' % good))
        self.assertEqual(lib3d.model_refs(both), ["TVS24A.stp", good])
        pretty = self.root / "lib_fp" / "lib_protection.pretty"
        lib3d.write_text(pretty / "TVS24A.kicad_mod", H.crlf(both))
        rep = lib3d.check_library(self.root)
        self.assertEqual([(r["kind"], r["fix_action"]) for r in rep["rows"]], [("bare", "remove"), ("ok", None)])
        self.assertEqual(lib3d.apply_fixes(self.root, rep["fixable"]),
                         ["lib_fp/lib_protection.pretty/TVS24A.kicad_mod"])
        text = lib3d.read_text(pretty / "TVS24A.kicad_mod")
        self.assertEqual(lib3d.model_refs(text), [good])
        self.assertTrue(balanced(text))
        self.assertNotIn("\n", text.replace("\r\n", ""))  # still all CRLF
        # Exactly the dead block's lines are gone: the rest is the original footprint.
        expected = H.crlf(both[:both.index("\t(model")] + both[both.index("\t(model", both.index("\t(model") + 1):])
        self.assertEqual(text, expected)
        self.assertEqual(lib3d.check_library(self.root)["counts"], {"ok": 1})

    def test_two_dead_refs_to_one_file_leave_one_block(self):
        pretty = self.root / "lib_fp" / "lib_protection.pretty"
        fp = H.FP_SAMACSYS.format(name="X", model="TVS24A.stp")
        extra = '  (model "D:\\\\old\\\\TVS24A.stp"\n    (at (xyz 0 0 0))\n    (scale (xyz 1 1 1))\n' \
                '    (rotate (xyz 0 0 0))\n  )\n'
        fp = fp[:fp.rstrip().rfind(")")] + extra + ")\n"
        lib3d.write_text(pretty / "X.kicad_mod", fp)
        rep = lib3d.check_library(self.root)
        self.assertEqual([r["fix_action"] for r in rep["fixable"]], ["rewrite", "remove"])
        lib3d.apply_fixes(self.root, rep["fixable"])
        text = lib3d.read_text(pretty / "X.kicad_mod")
        self.assertEqual(lib3d.model_refs(text), [self.cfg.library_mount + "/3d_models/TVS24A.stp"])
        self.assertTrue(balanced(text))

    def test_remove_model_block_inline(self):
        t = '(footprint "A" (layer "F.Cu") (model "x.stp" (offset (xyz 0 0 0))))\n'
        self.assertEqual(lib3d.remove_model_block(t, "x.stp"), '(footprint "A" (layer "F.Cu") )\n')
        self.assertEqual(lib3d.remove_model_block(t, "y.stp"), t)

    def test_only_category_libraries_are_checked_unless_all(self):
        other = self.root / "lib_fp" / "Vendor_Misc.pretty"
        other.mkdir()
        lib3d.write_text(other / "V.kicad_mod", H.FP_SAMACSYS.format(name="V", model="V.stp"))
        self.assertEqual(lib3d.check_library(self.root)["footprints"], 0)
        self.assertEqual(lib3d.check_library(self.root, all_libs=True)["footprints"], 1)


class MountLayout(unittest.TestCase):
    """Where the KiCad check puts its throwaway project and the mounted library (no KiCad needed)."""

    def setUp(self):
        import kicad_lib_verify
        self.layout = kicad_lib_verify.mount_layout
        self.work = os.path.abspath("work")

    def inside_work(self, path):
        return os.path.commonpath([self.work, os.path.abspath(path)]) == self.work

    def test_project_relative_mounts(self):
        w = self.work
        self.assertEqual(self.layout(w, "${KIPRJMOD}"), (w, w, {}))
        self.assertEqual(self.layout(w, "${KIPRJMOD}/kicad_library/"), (w, os.path.join(w, "kicad_library"), {}))
        project, mount_dir, env = self.layout(w, "${KIPRJMOD}/../../shared/partlib")
        self.assertEqual(project, os.path.join(w, "p", "p"))
        self.assertEqual(mount_dir, os.path.join(w, "shared", "partlib"))
        self.assertEqual(env, {})
        self.assertTrue(self.inside_work(mount_dir))

    def test_variable_mounts(self):
        w = self.work
        project, mount_dir, env = self.layout(w, "${MY_LIB}")
        self.assertEqual((project, mount_dir), (w, os.path.join(w, "env_MY_LIB")))
        self.assertEqual(env, {"MY_LIB": mount_dir})
        project, mount_dir, env = self.layout(w, "${MY_LIB}/../lib")
        self.assertEqual(env, {"MY_LIB": os.path.join(w, "env_MY_LIB", "p")})
        self.assertEqual(mount_dir, os.path.join(w, "env_MY_LIB", "lib"))

    def test_bad_mount(self):
        for mount in ("partlib", "D:/libs/partlib", "$KIPRJMOD/x"):
            with self.assertRaises(ValueError, msg=mount):
                self.layout(self.work, mount)


class CustomLayout(unittest.TestCase):
    """The same checks on a library with its own names and folders."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = H.make_library(self.tmp.name, prefix="acme_", symbol_dir="symbols", footprint_dir="footprints",
                                   model_dir="models")
        self.cfg = libcfg.LibraryConfig(self.root, library_prefix="acme_", symbol_dir="symbols",
                                        footprint_dir="footprints", model_dir="models",
                                        library_mount="${ACME_KICAD_LIB}")
        (self.root / "models" / "TVS24A.stp").write_bytes(H.FAKE_STEP)

    def tearDown(self):
        self.tmp.cleanup()

    def test_classify_and_fix_with_custom_mount(self):
        self.assertEqual(lib3d.classify_ref("${ACME_KICAD_LIB}/models/TVS24A.stp", self.cfg),
                         ("ok", "models/TVS24A.stp"))
        pretty = self.root / "footprints" / "acme_protection.pretty"
        lib3d.write_text(pretty / "TVS24A.kicad_mod", H.FP_SAMACSYS.format(name="TVS24A", model="TVS24A.stp"))
        # A footprint folder without the prefix is not a category library.
        (self.root / "footprints" / "lib_protection.pretty").mkdir()
        lib3d.write_text(self.root / "footprints" / "lib_protection.pretty" / "Y.kicad_mod",
                         H.FP_SAMACSYS.format(name="Y", model="Y.stp"))
        rep = lib3d.check_library(self.cfg)
        self.assertEqual(rep["footprints"], 1)
        self.assertEqual(rep["fixable"][0]["fix"], "${ACME_KICAD_LIB}/models/TVS24A.stp")
        lib3d.apply_fixes(self.cfg, rep["fixable"])
        self.assertEqual(lib3d.check_library(self.cfg)["counts"], {"ok": 1})

    def test_category_whose_name_lacks_the_prefix_is_checked(self):
        # A category may name its library anything (name = "legacy_logic"); its
        # footprints are category footprints all the same, and the CI gate must see them.
        cfg = libcfg.LibraryConfig(self.root, library_prefix="acme_", symbol_dir="symbols",
                                   footprint_dir="footprints", model_dir="models",
                                   library_mount="${ACME_KICAD_LIB}",
                                   categories=["ics", {"key": "logic", "name": "legacy_logic"}])
        pretty = self.root / "footprints" / "legacy_logic.pretty"
        pretty.mkdir()
        lib3d.write_text(pretty / "SOD.kicad_mod", H.FP_SAMACSYS.format(name="SOD", model="TVS24A.stp"))
        self.assertIn(pretty, lib3d.footprint_dirs(cfg))
        rep = lib3d.check_library(cfg)
        self.assertEqual(rep["footprints"], 1)
        self.assertEqual(rep["counts"], {"bare": 1})
        self.assertEqual(rep["fixable"][0]["footprint"], "footprints/legacy_logic.pretty/SOD.kicad_mod")
        # A category library that carries the prefix is listed once, not twice.
        dirs = lib3d.footprint_dirs(libcfg.LibraryConfig(self.root, library_prefix="acme_",
                                                         footprint_dir="footprints", categories=["protection"]))
        self.assertEqual(dirs, sorted(d for d in (self.root / "footprints").glob("acme_*.pretty")))


if __name__ == "__main__":
    unittest.main()
