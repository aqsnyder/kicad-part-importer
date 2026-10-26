"""Tests of the configuration: defaults, validation, where settings come from
(flags > environment > config file > defaults), and a library with its own
prefix, folders, mount and categories driven end to end."""
import json
import os
import tempfile
import unittest
from pathlib import Path

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg
import kicad_lib_stock as libstock
import kicad_part_importer as kpi

try:
    libcfg._toml_loads()
    HAVE_TOML = True
except libcfg.ConfigError:
    HAVE_TOML = False


class ScratchDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class Defaults(ScratchDirCase):
    def test_defaults(self):
        root = self.t / "partlib"
        cfg = libcfg.LibraryConfig(root)
        self.assertEqual(cfg.library_prefix, "lib_")
        self.assertEqual((cfg.symbol_dir, cfg.footprint_dir, cfg.model_dir), ("lib_sym", "lib_fp", "3d_models"))
        self.assertEqual(cfg.model_search_path, ("3d_models",))
        self.assertEqual(Path(cfg.project_dir), self.t.resolve())
        self.assertEqual(cfg.library_mount, "${KIPRJMOD}/partlib")
        self.assertEqual(cfg.model_prefix, "${KIPRJMOD}/partlib/3d_models")
        self.assertEqual([c.key for c in cfg.categories], H.CATEGORIES)
        self.assertEqual(cfg.categories[4].name, "lib_power_management")
        self.assertEqual(cfg.categories[4].sym_file, "lib_power_management.kicad_sym")
        self.assertEqual(cfg.categories[4].fp_dir, "lib_power_management.pretty")
        self.assertIn("Device", cfg.stock_symbol_libraries)

    def test_mount_follows_the_project_folder(self):
        root = self.t / "a" / "partlib"
        self.assertEqual(libcfg.LibraryConfig(root, project_dir=root).library_mount, "${KIPRJMOD}")
        self.assertEqual(libcfg.LibraryConfig(root, project_dir=self.t).library_mount, "${KIPRJMOD}/a/partlib")
        self.assertEqual(libcfg.LibraryConfig(root, project_dir=self.t / "b").library_mount,
                         "${KIPRJMOD}/../a/partlib")

    def test_model_prefix_follows_mount_and_model_dir(self):
        cfg = libcfg.LibraryConfig(self.t, library_mount="${MY_LIB}/", model_dir="models\\step")
        self.assertEqual(cfg.library_mount, "${MY_LIB}")
        self.assertEqual(cfg.model_prefix, "${MY_LIB}/models/step")

    def test_category_forms(self):
        cfg = libcfg.LibraryConfig(self.t, library_prefix="x_", categories=[
            "ics", ("power", "Power parts"), {"key": "misc", "description": "Other", "name": "Odds"}])
        self.assertEqual([(c.key, c.name, c.description) for c in cfg.categories],
                         [("ics", "x_ics", ""), ("power", "x_power", "Power parts"), ("misc", "Odds", "Other")])


class Validation(ScratchDirCase):
    def bad(self, **kw):
        with self.assertRaises(libcfg.ConfigError):
            libcfg.LibraryConfig(self.t, **kw)

    def test_mount_needs_a_path_variable(self):
        self.bad(library_mount="D:/libs/partlib")
        self.bad(library_mount="partlib")
        self.bad(library_mount="$KIPRJMOD/partlib")

    def test_names(self):
        self.bad(library_prefix="a/b")
        self.bad(library_prefix="a:b")
        self.bad(categories=[{"key": "a", "name": ""}])
        self.bad(categories=["1abc"])
        self.bad(categories=["a", "a"])
        self.bad(categories=[{"key": "a", "name": "n"}, {"key": "b", "name": "n"}])
        self.bad(categories=[])
        self.bad(categories=[{"key": "a", "colour": "red"}])
        self.bad(categories="connectors")

    def test_folders_stay_inside_the_library(self):
        for value in ("", ".", "..", "../x", "/abs", "D:/abs", "a/../.."):
            self.bad(model_dir=value)
        self.bad(model_search_dirs=["../elsewhere"])
        self.bad(model_search_dirs="vendor")

    def test_empty_prefix_is_allowed(self):
        cfg = libcfg.LibraryConfig(self.t, library_prefix="")
        self.assertEqual(cfg.categories[0].name, "connectors")


class Sources(ScratchDirCase):
    def setUp(self):
        super().setUp()
        self.root = self.t / "partlib"
        self.root.mkdir()

    def write_json(self, path, data):
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        return path

    def resolve(self, cli=None, env=None):
        cli = dict(cli or {})
        cli.setdefault("library_root", str(self.root))
        return libcfg.resolve_config(cli, environ=env or {}, cwd=self.t)

    def test_precedence_flags_over_environment_over_file(self):
        self.write_json(self.root / "kicad-part-importer.json", {"library_prefix": "file_", "model_dir": "m_file"})
        env = {"KICAD_PART_IMPORTER_LIBRARY_PREFIX": "env_"}
        self.assertEqual(self.resolve().library_prefix, "file_")
        self.assertEqual(self.resolve(env=env).library_prefix, "env_")
        cfg = self.resolve({"library_prefix": "cli_"}, env)
        self.assertEqual(cfg.library_prefix, "cli_")
        self.assertEqual(cfg.model_dir, "m_file")  # untouched settings still come from the file
        self.assertEqual(Path(cfg.config_file), self.root / "kicad-part-importer.json")

    def test_no_config_file_means_defaults(self):
        cfg = self.resolve()
        self.assertIsNone(cfg.config_file)
        self.assertEqual(cfg.library_prefix, "lib_")

    def test_library_root_from_environment_and_current_directory(self):
        env = {"KICAD_PART_IMPORTER_LIBRARY_ROOT": "partlib"}
        self.assertEqual(libcfg.resolve_config({}, environ=env, cwd=self.t).library_root, self.t / "partlib")
        self.assertEqual(libcfg.resolve_config({}, environ={}, cwd=self.root).library_root, self.root)

    def test_explicit_config_file_with_library_root(self):
        conf = self.t / "conf"
        conf.mkdir()
        self.write_json(conf / "mine.json", {"library_root": "../partlib", "project_dir": "../projects/board"})
        cfg = libcfg.resolve_config({"config": "conf/mine.json"}, environ={}, cwd=self.t)
        self.assertEqual(cfg.library_root.resolve(), self.root.resolve())
        self.assertEqual(Path(cfg.project_dir).resolve(), (self.t / "projects" / "board").resolve())
        self.assertEqual(cfg.library_mount, "${KIPRJMOD}/../../partlib")
        # The same file named by the environment variable.
        env = {"KICAD_PART_IMPORTER_CONFIG": str(conf / "mine.json")}
        self.assertEqual(libcfg.resolve_config({}, environ=env, cwd=self.t).library_root.resolve(),
                         self.root.resolve())

    def test_discovered_file_cannot_move_the_library_root(self):
        self.write_json(self.root / "kicad-part-importer.json", {"library_root": ".."})
        with self.assertRaises(libcfg.ConfigError):
            self.resolve()

    def test_two_discovered_files_are_an_error(self):
        self.write_json(self.root / "kicad-part-importer.json", {})
        (self.root / "kicad-part-importer.toml").write_text("", encoding="utf-8")
        with self.assertRaises(libcfg.ConfigError):
            self.resolve()

    def test_unknown_setting_and_bad_files(self):
        self.write_json(self.root / "kicad-part-importer.json", {"library_prefx": "x_"})
        with self.assertRaisesRegex(libcfg.ConfigError, "library_prefx"):
            self.resolve()
        (self.root / "kicad-part-importer.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(libcfg.ConfigError):
            self.resolve()
        self.write_json(self.t / "list.json", ["a"])
        with self.assertRaises(libcfg.ConfigError):
            self.resolve({"config": "list.json"})
        with self.assertRaises(libcfg.ConfigError):
            self.resolve({"config": "missing.json"})
        self.write_json(self.t / "conf.yaml", {})
        with self.assertRaises(libcfg.ConfigError):
            self.resolve({"config": "conf.yaml"})

    def test_model_search_dirs_from_environment(self):
        env = {"KICAD_PART_IMPORTER_MODEL_SEARCH_DIRS": os.pathsep.join(["vendor/a", "vendor/b"])}
        self.assertEqual(self.resolve(env=env).model_search_path, ("3d_models", "vendor/a", "vendor/b"))

    @unittest.skipUnless(HAVE_TOML, "no TOML parser (Python 3.11+ or tomli)")
    def test_toml_file(self):
        (self.root / "kicad-part-importer.toml").write_text(
            'library_prefix = "acme_"\n'
            'library_mount = "${KIPRJMOD}/acme_kicad_library"\n'
            'model_search_dirs = ["vendor/Parts.3dshapes"]\n'
            '\n[[categories]]\nkey = "ics"\ndescription = "Integrated circuits"\n'
            '\n[[categories]]\nkey = "power"\n', encoding="utf-8")
        cfg = self.resolve()
        self.assertEqual(cfg.library_prefix, "acme_")
        self.assertEqual(cfg.model_prefix, "${KIPRJMOD}/acme_kicad_library/3d_models")
        self.assertEqual(cfg.model_search_dirs, ("vendor/Parts.3dshapes",))
        self.assertEqual([(c.key, c.name) for c in cfg.categories], [("ics", "acme_ics"), ("power", "acme_power")])

    def test_example_config_parses(self):
        example = H.REPO / "examples" / "kicad-part-importer.json"
        cfg = libcfg.resolve_config({"config": str(example), "library_root": str(self.root)}, environ={}, cwd=self.t)
        self.assertEqual(len(cfg.categories), 13)

    @unittest.skipUnless(HAVE_TOML, "no TOML parser (Python 3.11+ or tomli)")
    def test_example_toml_config_parses(self):
        example = H.REPO / "examples" / "kicad-part-importer.toml"
        cfg = libcfg.resolve_config({"config": str(example), "library_root": str(self.root)}, environ={}, cwd=self.t)
        self.assertEqual(len(cfg.categories), 13)


class ConfigurablePrefix(ScratchDirCase):
    """A library whose category libraries are named acme_<key> instead of lib_<key>."""

    def setUp(self):
        super().setUp()
        self.lib = H.make_library(self.t / "acme_kicad_library", prefix="acme_")
        self.zips = self.t / "zips"
        self.zips.mkdir()

    def run_acme(self, *args, **kw):
        return H.run_importer("--library-root", self.lib, "--library-prefix", "acme_", *args, **kw)

    def test_import_link_refuse_and_check_with_a_custom_prefix(self):
        names = H.ti_zip(self.zips / "p.zip")
        r = self.run_acme(self.zips / "p.zip", "--category", "acme_power_management", "--link-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(rep["category"], "power_management")
        self.assertEqual(sorted(rep["written"]), sorted(
            ["3d_models/PKG0005A.stp", "lib_sym/acme_power_management.kicad_sym"] +
            ["lib_fp/acme_power_management.pretty/%s.kicad_mod" % n for n in names]))
        self.assertTrue(any("(KiCad needs acme_power_management:" in w for w in rep["warnings"]))
        text = lib3d.read_text(self.lib / "lib_fp" / "acme_power_management.pretty" / (names[0] + ".kicad_mod"))
        self.assertEqual(lib3d.model_refs(text), ["${KIPRJMOD}/acme_kicad_library/3d_models/PKG0005A.stp"])
        self.assertFalse(any(p.name.startswith("lib_") for p in (self.lib / "lib_sym").iterdir()))

        # The same symbol again: refused, naming the custom library.
        r = self.run_acme(self.zips / "p.zip", "--category", "power_management", "--yes", "--json")
        self.assertEqual(r.returncode, 3)
        self.assertIn("symbol TESTSW1 already exists in acme_power_management (remove or rename it first)",
                      json.loads(r.stdout)["errors"])
        # In another category: a warning that names the other custom library.
        r = self.run_acme(self.zips / "p.zip", "--category", "4", "--dry-run", "--json")
        self.assertIn("symbol TESTSW1 also exists in acme_power_management", json.loads(r.stdout)["warnings"])

        # --check-3d looks at acme_*.pretty only.
        (self.lib / "lib_fp" / "lib_protection.pretty").mkdir()
        lib3d.write_text(self.lib / "lib_fp" / "lib_protection.pretty" / "X.kicad_mod",
                         H.FP_SAMACSYS.format(name="X", model="X.stp"))
        r = self.run_acme("--check-3d", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["counts"], {"ok": 3})

    def test_default_prefix_does_not_see_the_custom_libraries(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "acme_power_management",
                           "--yes", "--json")
        self.assertEqual(r.returncode, 2)
        self.assertTrue(any("unknown category" in e for e in json.loads(r.stdout)["errors"]))

    def test_prefix_from_environment_and_config_file(self):
        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "acme_ics_general",
                           "--dry-run", "--json", env_extra={"KICAD_PART_IMPORTER_LIBRARY_PREFIX": "acme_"})
        self.assertEqual(r.returncode, 0, r.stderr)
        (self.lib / "kicad-part-importer.json").write_text(json.dumps({"library_prefix": "acme_"}), encoding="utf-8")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", "--category", "acme_ics_general",
                           "--dry-run", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["symbols"][0]["target"], "lib_sym/acme_ics_general.kicad_sym")


class CustomLayoutCLI(ScratchDirCase):
    """Own folders, mount, categories and model search folder, from a config file in the library root."""

    def setUp(self):
        super().setUp()
        self.lib = self.t / "parts"
        self.lib.mkdir()
        (self.lib / "kicad-part-importer.json").write_text(json.dumps({
            "library_prefix": "acme_",
            "symbol_dir": "symbols",
            "footprint_dir": "footprints",
            "model_dir": "models",
            "model_search_dirs": ["vendor/Parts.3dshapes"],
            "library_mount": "${KIPRJMOD}/acme_kicad_library",
            "categories": [
                {"key": "ics", "description": "Integrated circuits"},
                {"key": "power", "description": "Power parts"},
                "protection",
            ],
        }), encoding="utf-8")
        self.zips = self.t / "zips"
        self.zips.mkdir()

    def test_show_config(self):
        r = H.run_importer("--library-root", self.lib, "--show-config")
        self.assertEqual(r.returncode, 0, r.stderr)
        shown = json.loads(r.stdout)
        self.assertEqual(shown["model_prefix"], "${KIPRJMOD}/acme_kicad_library/models")
        self.assertEqual([c["name"] for c in shown["categories"]], ["acme_ics", "acme_power", "acme_protection"])
        self.assertTrue(shown["config_file"].endswith("kicad-part-importer.json"))
        r = H.run_importer("--library-root", self.lib, "--show-config", "--library-mount", "${ACME_LIB}")
        self.assertEqual(json.loads(r.stdout)["model_prefix"], "${ACME_LIB}/models")

    def test_init_then_import_with_the_custom_layout(self):
        r = H.run_importer("--library-root", self.lib, "--init-libraries")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in (self.lib / "symbols").iterdir()),
                         ["acme_ics.kicad_sym", "acme_power.kicad_sym", "acme_protection.kicad_sym"])
        self.assertTrue((self.lib / "footprints" / "acme_protection.pretty").is_dir())
        self.assertTrue((self.lib / "models").is_dir())

        H.ti_zip(self.zips / "p.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "p.zip", stdin="2\nn\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Enter your choice (0-3)", r.stdout)
        self.assertIn(" 3. Protection\n", r.stdout)
        self.assertIn('(symbol "TESTSW1"', lib3d.read_text(self.lib / "symbols" / "acme_power.kicad_sym"))
        self.assertTrue((self.lib / "models" / "PKG0005A.stp").exists())

        H.samacsys_zip(self.zips / "s.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "s.zip", "--category", "protection",
                           "--link-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        text = lib3d.read_text(self.lib / "footprints" / "acme_protection.pretty" / "DIONTEST.kicad_mod")
        self.assertEqual(lib3d.model_refs(text), ["${KIPRJMOD}/acme_kicad_library/models/TESTTVS.stp"])

        r = H.run_importer("--library-root", self.lib, self.zips / "s.zip", "--category", "sensors", "--yes",
                           "--json")
        self.assertEqual(r.returncode, 2)
        self.assertIn("one of: ics, power, protection", json.loads(r.stdout)["errors"][0])

    def test_fix_finds_models_in_a_search_folder(self):
        H.run_importer("--library-root", self.lib, "--init-libraries")
        shapes = self.lib / "vendor" / "Parts.3dshapes"
        shapes.mkdir(parents=True)
        (shapes / "OLD.stp").write_bytes(H.FAKE_STEP)
        fp = self.lib / "footprints" / "acme_ics.pretty" / "OLD.kicad_mod"
        lib3d.write_text(fp, H.FP_SAMACSYS.format(name="OLD", model="D:/somewhere/OLD.stp"))
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--fix-3d", "--yes", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(lib3d.model_refs(lib3d.read_text(fp)),
                         ["${KIPRJMOD}/acme_kicad_library/vendor/Parts.3dshapes/OLD.stp"])

    def test_bad_config_is_a_usage_error(self):
        (self.lib / "kicad-part-importer.json").write_text(json.dumps({"library_mount": "D:/abs"}), encoding="utf-8")
        r = H.run_importer("--library-root", self.lib, "--check-3d")
        self.assertEqual(r.returncode, 2)
        self.assertIn("library_mount", r.stderr)

    def test_check_3d_covers_a_category_named_without_the_prefix(self):
        cfg = json.loads((self.lib / "kicad-part-importer.json").read_text(encoding="utf-8"))
        cfg["categories"].append({"key": "logic", "name": "legacy_logic"})
        (self.lib / "kicad-part-importer.json").write_text(json.dumps(cfg), encoding="utf-8")
        H.run_importer("--library-root", self.lib, "--init-libraries")
        H.samacsys_zip(self.zips / "s.zip")
        r = H.run_importer("--library-root", self.lib, self.zips / "s.zip", "--category", "logic", "--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.lib / "footprints" / "legacy_logic.pretty" / "DIONTEST.kicad_mod").is_file())
        # Imported without --link-3d: the bare model name is a problem the check must report.
        r = H.run_importer("--library-root", self.lib, "--check-3d", "--json")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual((rep["footprints"], rep["counts"]), (1, {"bare": 1}))
        # ... and the import's "also exists in" warning looks there too.
        r = H.run_importer("--library-root", self.lib, self.zips / "s.zip", "--category", "protection",
                           "--dry-run", "--json")
        self.assertIn("footprint DIONTEST also exists in legacy_logic.pretty", json.loads(r.stdout)["warnings"])


class ProjectTables(ScratchDirCase):
    def test_add_to_project_uses_the_project_dir(self):
        project = self.t / "boards" / "board1"
        project.mkdir(parents=True)
        (project / "sym-lib-table").write_text("(sym_lib_table\n  (version 7)\n)\n", encoding="utf-8")
        (project / "fp-lib-table").write_text("(fp_lib_table\n  (version 7)\n)\n", encoding="utf-8")
        lib = H.make_library(self.t / "partlib")
        r = H.run_importer("--library-root", lib, "--project-dir", project, "--add-to-project", stdin="5\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sym = (project / "sym-lib-table").read_text(encoding="utf-8")
        fp = (project / "fp-lib-table").read_text(encoding="utf-8")
        self.assertIn('(lib (name "lib_power_management")(type "KiCad")'
                      '(uri "${KIPRJMOD}/../../partlib/lib_sym/lib_power_management.kicad_sym")', sym)
        self.assertIn('(uri "${KIPRJMOD}/../../partlib/lib_fp/lib_power_management.pretty")', fp)
        self.assertNotIn("lib_connectors", sym)

    def make_project(self, eol="\n"):
        project = self.t / "board"
        project.mkdir()
        for name, head in (("sym-lib-table", "sym_lib_table"), ("fp-lib-table", "fp_lib_table")):
            with open(project / name, "w", encoding="utf-8", newline="") as fh:
                fh.write(("(%s\n  (version 7)\n"
                          '  (lib (name "Stock")(type "KiCad")(uri "${KICAD9_SYMBOL_DIR}/Stock")(options "")(descr ""))\n'
                          ")\n" % head).replace("\n", eol))
        return project

    def test_running_twice_adds_nothing_twice(self):
        project = self.make_project()
        lib = H.make_library(project / "partlib")
        for stdin in ("5\n", "5,1\n", "0\n"):
            r = H.run_importer("--library", lib, "--add-to-project", stdin=stdin)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sym = (project / "sym-lib-table").read_text(encoding="utf-8")
        self.assertEqual(sym.count('(name "lib_power_management")'), 1)
        self.assertEqual(sym.count('(name "lib_connectors")'), 1)
        self.assertEqual(sym.count("(lib (name"), 14)  # the stock entry + 13 categories
        self.assertIn('(uri "${KIPRJMOD}/partlib/lib_sym/lib_power_management.kicad_sym")(options "")'
                      '(descr "Power management ICs, regulators, and converters"))', sym)
        self.assertIn("already exists: lib_power_management", r.stdout)

    def test_tables_use_the_library_mount_and_keep_crlf(self):
        project = self.make_project(eol="\r\n")
        lib = H.make_library(self.t / "shared" / "acme_lib")
        r = H.run_importer("--library", lib, "--project-dir", project, "--library-mount", "${ACME_KICAD_LIB}",
                           "--add-to-project", stdin="2\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        raw = (project / "fp-lib-table").read_bytes()
        self.assertIn(b'(uri "${ACME_KICAD_LIB}/lib_fp/lib_passives.pretty")', raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))  # CRLF kept, no bare LF added


class SchematicFilter(ScratchDirCase):
    def components(self, *lib_names):
        return [{"lib_id": n + ":X", "lib_name": n, "sym_name": "X", "footprint": ""} for n in lib_names]

    def manager(self, **settings):
        """A LibraryManager that sees no KiCad: only the configured list is stock."""
        cfg = libcfg.LibraryConfig(self.t, **settings)
        return kpi.LibraryManager(config=cfg, stock=libstock.StockSymbolLibraries(cfg.stock_symbol_libraries))

    def test_prefix_and_stock_libraries_are_left_alone(self):
        m = self.manager()
        kept = m.custom_schematic_components(self.components("Device", "lib_passives", "lib_other", "MyParts"))
        self.assertEqual([c["lib_name"] for c in kept], ["MyParts"])

    def test_empty_prefix_does_not_hide_everything(self):
        m = self.manager(library_prefix="")
        kept = m.custom_schematic_components(self.components("Device", "passives", "MyParts"))
        self.assertEqual([c["lib_name"] for c in kept], ["MyParts"])

    def test_stock_libraries_are_configurable(self):
        m = self.manager(stock_symbol_libraries=["MyParts"])
        kept = m.custom_schematic_components(self.components("Device", "MyParts"))
        self.assertEqual([c["lib_name"] for c in kept], ["Device"])

    def test_kicad_libraries_are_left_alone_without_the_list(self):
        installed = self.t / "symbols"
        H.write_eol(installed / "Sensor_Humidity.kicad_sym", H.EMPTY_LIB)
        m = kpi.LibraryManager(config=libcfg.LibraryConfig(self.t, stock_symbol_libraries=[]),
                               stock=libstock.StockSymbolLibraries(symbol_dirs=[installed]))
        table = {"74xGxx": "${KICAD10_SYMBOL_DIR}/74xGxx.kicad_sym", "Mine": "${KIPRJMOD}/Mine.kicad_sym"}
        kept = m.custom_schematic_components(self.components("Sensor_Humidity", "74xGxx", "Mine", "Ghost"), table)
        self.assertEqual([c["lib_name"] for c in kept], ["Mine", "Ghost"])


class Packaging(unittest.TestCase):
    def test_version_matches_pyproject(self):
        text = (H.REPO / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('\nversion = "%s"\n' % kpi.__version__, text)

    def test_version_flag(self):
        r = H.run_importer("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn(kpi.__version__, r.stdout)


if __name__ == "__main__":
    unittest.main()
