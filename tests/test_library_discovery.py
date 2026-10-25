"""Which library the tool works on, and `--init`.

The library root comes from --library, then KICAD_PART_IMPORTER_LIBRARY_ROOT,
then the nearest folder at or above the current directory holding a config
file (as git finds .git), then the current directory. `--init` writes a config
file that every later command reads back."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg

HAVE_TOML = libcfg.toml_reader() is not None
# Settings --show-config prints that describe where they came from, not the library.
PROVENANCE = ("config_file", "library_root_source")


def same_dir(a, b):
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


class ScratchDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.zips = self.t / "zips"
        self.zips.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def show(self, *args, cwd=None, env_extra=None):
        r = H.run_importer("--show-config", *args, cwd=cwd, env_extra=env_extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)


class UpwardDiscovery(ScratchDirCase):
    def setUp(self):
        super().setUp()
        self.lib = H.make_library(self.t / "acme_kicad_library", prefix="acme_")
        (self.lib / "kicad-part-importer.json").write_text(json.dumps({"library_prefix": "acme_"}),
                                                           encoding="utf-8")
        self.deep = self.lib / "lib_fp" / "acme_power_management.pretty"

    def test_found_from_a_subfolder(self):
        shown = self.show(cwd=self.deep)
        self.assertTrue(same_dir(shown["library_root"], self.lib))
        self.assertEqual(shown["library_root_source"], "discovered")
        self.assertEqual(shown["library_prefix"], "acme_")
        self.assertTrue(shown["config_file"].endswith("kicad-part-importer.json"))

    def test_import_from_a_subfolder_writes_into_the_library(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer(self.zips / "p.zip", "--category", "power_management", "--link-3d", "--yes", "--json",
                           cwd=self.deep)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('(symbol "TESTSW1"', lib3d.read_text(self.lib / "lib_sym" / "acme_power_management.kicad_sym"))
        self.assertTrue((self.lib / "3d_models" / "PKG0005A.stp").is_file())
        self.assertFalse((self.deep / "lib_sym").exists())

    def test_nearest_config_wins(self):
        inner = H.make_library(self.lib / "vendor" / "inner")
        (inner / "kicad-part-importer.json").write_text(json.dumps({"library_prefix": "lib_"}), encoding="utf-8")
        shown = self.show(cwd=inner / "lib_sym")
        self.assertTrue(same_dir(shown["library_root"], inner))
        self.assertEqual(shown["library_prefix"], "lib_")

    def test_flag_and_environment_beat_discovery(self):
        other = H.make_library(self.t / "other")
        shown = self.show("--library", other, cwd=self.deep)
        self.assertTrue(same_dir(shown["library_root"], other))
        self.assertEqual((shown["library_root_source"], shown["library_prefix"]), ("command line", "lib_"))
        shown = self.show("--library-root", other, cwd=self.deep)  # the older spelling still works
        self.assertTrue(same_dir(shown["library_root"], other))
        shown = self.show(cwd=self.deep, env_extra={"KICAD_PART_IMPORTER_LIBRARY_ROOT": str(other)})
        self.assertTrue(same_dir(shown["library_root"], other))
        self.assertEqual(shown["library_root_source"], "environment")

    def test_explicit_config_file_turns_discovery_off(self):
        conf = self.t / "elsewhere.json"
        conf.write_text(json.dumps({"library_prefix": "x_"}), encoding="utf-8")
        shown = self.show("--config", conf, cwd=self.deep)
        self.assertTrue(same_dir(shown["library_root"], self.deep))
        self.assertEqual((shown["library_root_source"], shown["library_prefix"]), ("current directory", "x_"))

    def test_resolve_config_unit(self):
        cfg = libcfg.resolve_config({}, environ={}, cwd=self.deep)
        self.assertTrue(same_dir(cfg.library_root, self.lib))
        self.assertEqual(cfg.library_root_source, "discovered")
        cfg = libcfg.resolve_config({}, environ={}, cwd=self.deep, discover=False)
        self.assertEqual((cfg.library_root, cfg.library_root_source), (self.deep, "current directory"))
        self.assertTrue(same_dir(libcfg.find_library_root(self.deep), self.lib))


class NoLibrary(ScratchDirCase):
    def test_falls_back_to_the_current_directory(self):
        here = self.t / "plain"
        here.mkdir()
        if libcfg.find_library_root(here) is not None:
            self.skipTest("a kicad-part-importer config file sits above the temporary folder")
        cfg = libcfg.resolve_config({}, environ={}, cwd=here)
        self.assertEqual((cfg.library_root, cfg.library_root_source), (here, "current directory"))
        shown = self.show(cwd=here)
        self.assertTrue(same_dir(shown["library_root"], here))
        self.assertEqual((shown["library_root_source"], shown["config_file"]), ("current directory", None))

    def test_commands_refuse_a_folder_that_is_not_a_library(self):
        here = self.t / "plain"
        here.mkdir()
        H.ti_zip(self.zips / "p.zip")
        for args in (("--check-3d",), (self.zips / "p.zip", "--category", "1", "--yes"),
                     (self.zips / "p.zip",), ("--add-to-project",)):
            r = H.run_importer("--library", here, *args, stdin="1\nn\n")
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
            self.assertIn("is not a part library", r.stderr)
            self.assertIn("--init", r.stderr)
        r = H.run_importer("--library", here, "--check-3d", "--json")
        self.assertEqual(r.returncode, 2)
        rep = json.loads(r.stdout)
        self.assertFalse(rep["ok"])
        self.assertIn("is not a part library", rep["errors"][0])
        self.assertEqual(list(here.iterdir()), [])  # nothing was created


class Init(ScratchDirCase):
    SETTINGS = ("--library-prefix", "acme_", "--model-dir", "models", "--model-search-dir", "vendor/old.3dshapes",
                "--library-mount", "${ACME_KICAD_LIB}", "--symbol-dir", "symbols", "--footprint-dir", "footprints")
    ENV = {"KICAD_PART_IMPORTER_GIT_COMMIT": "true", "KICAD_PART_IMPORTER_GIT_MESSAGE_PREFIX": "parts: "}

    def roundtrip(self, fmt):
        lib = self.t / ("lib_" + fmt)
        # What the flags and variables mean before any file exists ...
        before = self.show("--library", lib, *self.SETTINGS, env_extra=self.ENV)
        r = H.run_importer("--init", "--library", lib, "--config-format", fmt, *self.SETTINGS, env_extra=self.ENV)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        cfg_file = lib / ("kicad-part-importer." + fmt)
        self.assertTrue(cfg_file.is_file())
        self.assertNotIn(b"\r\n", cfg_file.read_bytes())
        # ... is what the file alone says afterwards, read from a subfolder with no flags or variables.
        after = self.show(cwd=lib / "footprints" / "acme_passives.pretty")
        self.assertEqual(after["library_root_source"], "discovered")
        self.assertTrue(same_dir(after["config_file"], cfg_file))
        for k in PROVENANCE + ("library_root", "project_dir"):
            self.assertTrue(k in before and k in after, k)
        self.assertTrue(same_dir(after["library_root"], before["library_root"]))
        self.assertTrue(same_dir(after["project_dir"], before["project_dir"]))
        strip = PROVENANCE + ("library_root", "project_dir")
        self.assertEqual({k: v for k, v in after.items() if k not in strip},
                         {k: v for k, v in before.items() if k not in strip})
        self.assertEqual((after["library_prefix"], after["model_prefix"], after["git_commit"],
                          after["git_message_prefix"]), ("acme_", "${ACME_KICAD_LIB}/models", True, "parts: "))
        # The layout exists.
        self.assertTrue((lib / "symbols" / "acme_power_management.kicad_sym").is_file())
        self.assertTrue((lib / "footprints" / "acme_power_management.pretty").is_dir())
        self.assertTrue((lib / "models").is_dir())

    def test_init_json_round_trips_through_show_config(self):
        self.roundtrip("json")

    @unittest.skipUnless(HAVE_TOML, "no TOML parser (Python 3.11+ or tomli)")
    def test_init_toml_round_trips_through_show_config(self):
        self.roundtrip("toml")

    def test_default_init_in_the_current_directory(self):
        lib = self.t / "my_kicad_library"
        lib.mkdir()
        r = H.run_importer("--init", cwd=lib)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = libcfg.config_files_in(lib)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].suffix, ".toml" if HAVE_TOML else ".json")
        shown = self.show(cwd=lib)
        self.assertEqual(shown["library_mount"], "${KIPRJMOD}/my_kicad_library")
        self.assertEqual([c["key"] for c in shown["categories"]], H.CATEGORIES)
        self.assertEqual(len(list((lib / "lib_sym").glob("lib_*.kicad_sym"))), 13)
        # The new library imports right away, from inside it.
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer(self.zips / "p.zip", "--category", "ics_general", "--link-3d", "--yes", cwd=lib / "lib_fp")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_existing_library_becomes_self_describing(self):
        lib = self.t / "acme_kicad_library"
        (lib / "lib_sym").mkdir(parents=True)
        (lib / "lib_fp" / "acme_power.pretty").mkdir(parents=True)
        (lib / "lib_fp" / "acme_74xx.pretty").mkdir(parents=True)
        sym = lib / "lib_sym" / "acme_ics.kicad_sym"
        sym.write_text(H.SYMBOL.format(name="KEEPME", fp="acme_ics:X"), encoding="utf-8")
        before = sym.read_bytes()
        r = H.run_importer("--init", "--library", lib, "--library-prefix", "acme_", "--config-format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        written = json.loads((lib / "kicad-part-importer.json").read_text(encoding="utf-8"))
        self.assertEqual(written["categories"], [{"key": "c_74xx", "name": "acme_74xx"}, {"key": "ics"},
                                                 {"key": "power"}])
        self.assertEqual(sym.read_bytes(), before)  # existing libraries are never rewritten
        self.assertTrue((lib / "lib_sym" / "acme_power.kicad_sym").is_file())
        shown = self.show(cwd=lib)
        self.assertEqual([c["name"] for c in shown["categories"]], ["acme_74xx", "acme_ics", "acme_power"])

    def test_existing_config_is_kept_and_not_contradicted(self):
        lib = self.t / "lib"
        self.assertEqual(H.run_importer("--init", "--library", lib, "--config-format", "json").returncode, 0)
        cfg_file = lib / "kicad-part-importer.json"
        text = cfg_file.read_bytes()
        r = H.run_importer("--init", "--library", lib)  # again: nothing to do, file kept
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already exists; kept it", r.stdout)
        r = H.run_importer("--init", "--library", lib, "--library-prefix", "xx_")
        self.assertEqual(r.returncode, 2)
        self.assertIn("does not change it", r.stderr)
        self.assertEqual(cfg_file.read_bytes(), text)
        self.assertFalse(list((lib / "lib_sym").glob("xx_*")))

    def test_init_inside_another_library_needs_library_flag(self):
        outer = self.t / "outer"
        self.assertEqual(H.run_importer("--init", "--library", outer).returncode, 0)
        inner = outer / "sub"
        inner.mkdir()
        r = H.run_importer("--init", cwd=inner)
        self.assertEqual(r.returncode, 2)
        self.assertIn("is inside the library", r.stderr)
        self.assertEqual(libcfg.config_files_in(inner), [])
        r = H.run_importer("--init", "--library", inner, cwd=inner)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(libcfg.config_files_in(inner)), 1)

    def test_template_config_seeds_a_new_library(self):
        template = self.t / "company-template.json"
        template.write_text(json.dumps({"library_prefix": "acme_", "git_message_prefix": "lib: ",
                                        "categories": [{"key": "ics", "description": "ICs"}, "power"]}),
                            encoding="utf-8")
        lib = self.t / "new_lib"
        r = H.run_importer("--init", "--library", lib, "--config", template, "--config-format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shown = self.show(cwd=lib)
        self.assertEqual([(c["key"], c["name"], c["description"]) for c in shown["categories"]],
                         [("ics", "acme_ics", "ICs"), ("power", "acme_power", "")])
        self.assertEqual(shown["git_message_prefix"], "lib: ")

    def test_template_model_prefix_and_project_dir_are_kept(self):
        # Every setting the template names is written as given, not commented out.
        tpl_dir = self.t / "tpl"
        tpl_dir.mkdir()
        template = tpl_dir / "acme-template.json"
        template.write_text(json.dumps({"library_prefix": "acme_", "model_prefix": "${ACME_MODELS}",
                                        "project_dir": "boards/main"}), encoding="utf-8")
        fmts = ("json", "toml") if HAVE_TOML else ("json",)
        for fmt in fmts:
            with self.subTest(fmt=fmt):
                lib = tpl_dir / ("newlib_" + fmt)
                r = H.run_importer("--init", "--library", lib, "--config", template, "--config-format", fmt)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                shown = self.show(cwd=lib)
                self.assertEqual(shown["model_prefix"], "${ACME_MODELS}")
                self.assertTrue(same_dir(shown["project_dir"], tpl_dir / "boards" / "main"))
                self.assertEqual(shown["library_prefix"], "acme_")

    def test_init_keeps_known_categories_with_their_descriptions_and_order(self):
        # A library made with the default names (here by --init-libraries) keeps the
        # default menu: same numbers for --category N, descriptions kept.
        lib = self.t / "defaults"
        (lib / "lib_sym").mkdir(parents=True)
        r = H.run_importer("--library", lib, "--init-libraries")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        before = self.show("--library", lib)["categories"]
        r = H.run_importer("--init", "--library", lib, "--config-format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        after = self.show(cwd=lib)["categories"]
        self.assertEqual(after, before)
        self.assertEqual(after[4]["key"], "power_management")
        self.assertTrue(all(c["description"] for c in after))

    def test_init_appends_unknown_libraries_after_the_known_ones(self):
        lib = self.t / "mixed"
        (lib / "lib_sym").mkdir(parents=True)
        for name in ("lib_zeta", "lib_passives", "lib_connectors", "lib_alpha"):
            (lib / "lib_sym" / (name + ".kicad_sym")).write_text(H.EMPTY_LIB, encoding="utf-8")
        r = H.run_importer("--init", "--library", lib, "--config-format", "json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        written = json.loads((lib / "kicad-part-importer.json").read_text(encoding="utf-8"))["categories"]
        self.assertEqual([c["key"] for c in written], ["connectors", "passives", "alpha", "zeta"])
        self.assertEqual(written[1]["description"], "Resistors, capacitors, inductors, and other passive components")
        self.assertNotIn("description", written[2])

    def test_init_runs_alone(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--init", "--library", self.t / "x", self.zips / "p.zip")
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.t / "x").exists())


class StarterConfigText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "lib"

    def tearDown(self):
        self.tmp.cleanup()

    def test_odd_strings_survive_both_formats(self):
        cfg = libcfg.LibraryConfig(self.root, git_message_prefix='say "hi" \\ \t\x7fé: ',
                                   categories=[("ics", 'Quotes " and \\ backslashes'), ("odd", "", "Odd Name")])
        fmts = ("json", "toml") if HAVE_TOML else ("json",)
        for fmt in fmts:
            with self.subTest(fmt=fmt):
                path = self.root / ("kicad-part-importer." + fmt)
                self.root.mkdir(exist_ok=True)
                path.write_text(libcfg.starter_config(cfg, fmt=fmt), encoding="utf-8")
                back = libcfg.resolve_config({"library_root": str(self.root)}, environ={}, cwd=self.root)
                self.assertEqual(back.git_message_prefix, cfg.git_message_prefix)
                self.assertEqual([c.to_dict() for c in back.categories], [c.to_dict() for c in cfg.categories])
                self.assertEqual(back.library_mount, cfg.library_mount)
                path.unlink()


class GitAndKiCadSettings(unittest.TestCase):
    def test_boolean_environment_values(self):
        for text, value in (("1", True), ("YES", True), ("on", True), ("0", False), ("false", False), ("", False)):
            cfg = libcfg.resolve_config({}, environ={"KICAD_PART_IMPORTER_GIT_COMMIT": text}, cwd=H.REPO,
                                        discover=False)
            self.assertIs(cfg.git_commit, value, text)
        with self.assertRaises(libcfg.ConfigError):
            libcfg.resolve_config({}, environ={"KICAD_PART_IMPORTER_GIT_PUSH": "maybe"}, cwd=H.REPO, discover=False)

    def test_git_settings_must_be_booleans_in_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "kicad-part-importer.json").write_text(json.dumps({"git_commit": "yes"}), encoding="utf-8")
            with self.assertRaisesRegex(libcfg.ConfigError, "git_commit"):
                libcfg.resolve_config({"library_root": d}, environ={}, cwd=d)

    def test_kicad_bin_is_authoritative(self):
        # KICAD_BIN (or --kicad-bin) pointing at a folder without kicad-cli hides
        # every installed KiCad: no fallback to the default install or PATH.
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"KICAD_BIN": os.path.join(d, "nonexistent")}):
                with self.assertRaisesRegex(RuntimeError, "no kicad-cli in KICAD_BIN"):
                    lib3d.find_kicad()
                with self.assertRaisesRegex(RuntimeError, "no kicad-cli in --kicad-bin"):
                    lib3d.find_kicad(d)


if __name__ == "__main__":
    unittest.main()
