"""Which symbol libraries are KiCad's own (kicad_lib_stock), so that
--migrate-schematic leaves their parts alone: the project's sym-lib-table,
KiCad's global one (with KiCad 10's nested default table), the installed
symbols folder, and the stock_symbol_libraries list. Every KiCad here is made
up under a scratch folder; one test also checks the default list against a
real KiCad when one is installed."""
import json
import tempfile
import unittest
from pathlib import Path

import libtest_helpers as H
import kicad_lib_3d as lib3d
import kicad_lib_config as libcfg
import kicad_lib_stock as libstock


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class Rules(Base):
    def test_a_stock_path_variable_marks_a_library_stock(self):
        stock = libstock.StockSymbolLibraries()
        for uri in ("${KICAD10_SYMBOL_DIR}/Device.kicad_sym", "${KICAD9_SYMBOL_DIR}/Device.kicad_sym",
                    "${KICAD8_SYMBOL_DIR}/Device.kicad_sym", "${KICAD_SYMBOL_DIR}/Device.lib"):
            self.assertTrue(stock.is_stock_uri(uri), uri)
        for uri in ("${KIPRJMOD}/Device.kicad_sym", "${KICAD10_3DMODEL_DIR}/x.step", "/opt/lib/Device.kicad_sym",
                    "${MY_KICAD10_SYMBOL_DIR}/Device.kicad_sym"):
            self.assertFalse(stock.is_stock_uri(uri), uri)

    def test_a_path_inside_the_symbols_folder_is_stock(self):
        symbols = self.t / "kicad" / "symbols"
        symbols.mkdir(parents=True)
        stock = libstock.StockSymbolLibraries(symbol_dirs=[symbols], variables={"KICAD_HOME": str(self.t / "kicad")})
        self.assertTrue(stock.is_stock_uri((symbols / "Device.kicad_sym").as_posix()))
        self.assertTrue(stock.is_stock_uri("${KICAD_HOME}/symbols/Device.kicad_sym"))
        self.assertFalse(stock.is_stock_uri((self.t / "kicad" / "symbols_old" / "Device.kicad_sym").as_posix()))
        self.assertFalse(stock.is_stock_uri("${UNSET}/symbols/Device.kicad_sym"))
        self.assertFalse(stock.is_stock_uri("symbols/Device.kicad_sym"))

    def test_the_project_table_decides(self):
        symbols = self.t / "symbols"
        H.write_eol(symbols / "Device.kicad_sym", H.EMPTY_LIB)
        stock = libstock.StockSymbolLibraries(global_table={"Device": "${KICAD10_SYMBOL_DIR}/Device.kicad_sym"},
                                              symbol_dirs=[symbols])
        self.assertTrue(stock.is_stock("Device"))
        self.assertTrue(stock.is_stock("Device", {"Device": "${KICAD9_SYMBOL_DIR}/Device.kicad_sym"}))
        # A project library of the same name, with a file of its own: the project's copy is used.
        self.assertFalse(stock.is_stock("Device", {"Device": "${KIPRJMOD}/Device.kicad_sym"}))

    def test_the_list_overrides_the_tables(self):
        stock = libstock.StockSymbolLibraries(["Device", "TeamShared"])
        self.assertTrue(stock.is_stock("Device", {"Device": "${KIPRJMOD}/Device.kicad_sym"}))
        self.assertTrue(stock.is_stock("TeamShared", {"TeamShared": "${TEAM}/TeamShared.kicad_sym"}))
        self.assertFalse(stock.is_stock("Other"))

    def test_installed_names(self):
        symbols = self.t / "symbols"
        for name in ("Sensor_Humidity.kicad_sym", "74xGxx.kicad_sym", "Simulation_SPICE.sp"):
            H.write_eol(symbols / name, H.EMPTY_LIB)
        (symbols / "Big.kicad_symdir").mkdir()
        (symbols / "NotAFile.kicad_sym").mkdir()
        stock = libstock.StockSymbolLibraries(symbol_dirs=[symbols, self.t / "missing"])
        self.assertEqual(stock.installed, {"Sensor_Humidity", "74xGxx", "Big"})
        self.assertTrue(stock.is_stock("74xGxx"))
        self.assertFalse(stock.is_stock("MCU_ST_STM32"))

    def test_a_global_entry_elsewhere_does_not_hide_an_installed_name(self):
        # The migration copies only from the project's table, so a global entry
        # that points elsewhere cannot make a library migratable.
        symbols = self.t / "symbols"
        H.write_eol(symbols / "Device.kicad_sym", H.EMPTY_LIB)
        stock = libstock.StockSymbolLibraries(global_table={"Device": "${MY_LIBS}/Device.kicad_sym",
                                                            "Mine": "${MY_LIBS}/Mine.kicad_sym"},
                                              symbol_dirs=[symbols])
        self.assertTrue(stock.is_stock("Device"))
        self.assertFalse(stock.is_stock("Mine"))


class Discovery(Base):
    def test_settings_folders_newest_first(self):
        home = self.t / "cfg"
        for v in ("8.0", "10.0", "9.0", "10.99", "backup", "9"):
            (home / v).mkdir(parents=True)
        dirs = libstock.config_dirs({"KICAD_CONFIG_HOME": str(home)})
        self.assertEqual([d.name for d in dirs], ["10.99", "10.0", "9.0", "8.0"])

    def test_global_table_follows_nested_tables(self):
        env = H.kicad_env(self.t, global_libs=("74xGxx", "Sensor_Optical"))
        configs = libstock.config_dirs(env)
        variables = libstock.path_variables(env, configs)
        # A user library next to the nested default table, and a table that nests itself.
        table = Path(env["KICAD_CONFIG_HOME"]) / "10.0" / "sym-lib-table"
        text = table.read_text(encoding="utf-8").replace(
            "\n)", '\n  (lib (name "Mine")(type "KiCad")(uri "${MY_LIBS}/Mine.kicad_sym")(options "")(descr ""))'
                   '\n  (lib (name "Loop")(type "Table")(uri "sym-lib-table")(options "")(descr ""))\n)')
        H.write_eol(table, text)
        found = libstock.global_lib_table(configs, variables)
        self.assertEqual(found, {"74xGxx": "${KICAD10_SYMBOL_DIR}/74xGxx.kicad_sym",
                                 "Sensor_Optical": "${KICAD10_SYMBOL_DIR}/Sensor_Optical.kicad_sym",
                                 "Mine": "${MY_LIBS}/Mine.kicad_sym"})

    def test_every_version_is_read_newest_first(self):
        env = H.kicad_env(self.t)
        home = Path(env["KICAD_CONFIG_HOME"])
        H.write_eol(home / "10.0" / "sym-lib-table",
                    H.lib_table("sym", [("Device", "${KICAD10_SYMBOL_DIR}/Device.kicad_sym")]))
        H.write_eol(home / "9.0" / "sym-lib-table",
                    H.lib_table("sym", [("Device", "${KICAD9_SYMBOL_DIR}/Device.kicad_sym"),
                                        ("Old9", "${KICAD9_SYMBOL_DIR}/Old9.kicad_sym")]))
        stock = libstock.StockSymbolLibraries.detect(environ=env)
        self.assertEqual(stock.global_table["Device"], "${KICAD10_SYMBOL_DIR}/Device.kicad_sym")
        self.assertTrue(stock.is_stock("Old9"))

    def test_symbol_folder_variables(self):
        ten, nine = self.t / "ten", self.t / "nine"
        ten.mkdir()
        nine.mkdir()
        env = {"KICAD9_SYMBOL_DIR": str(nine), "KICAD10_SYMBOL_DIR": str(ten), "KICAD8_SYMBOL_DIR": str(self.t / "no")}
        self.assertEqual(libstock.symbol_dirs(env, env), [ten, nine])  # newest first; a missing folder is skipped

    def test_kicad_preferences_set_path_variables_and_the_environment_wins(self):
        home = self.t / "cfg"
        (home / "10.0").mkdir(parents=True)
        (home / "10.0" / "kicad_common.json").write_text(json.dumps(
            {"environment": {"vars": {"KICAD10_SYMBOL_DIR": "/from/prefs", "MY_LIBS": "/libs"}}}), encoding="utf-8")
        (home / "9.0").mkdir()
        (home / "9.0" / "kicad_common.json").write_text(json.dumps(
            {"environment": {"vars": {"OLD9": "/old"}}}), encoding="utf-8")
        variables = libstock.path_variables({"KICAD_CONFIG_HOME": str(home), "MY_LIBS": "/env"})
        self.assertEqual(variables["KICAD10_SYMBOL_DIR"], "/from/prefs")
        self.assertEqual(variables["MY_LIBS"], "/env")
        self.assertNotIn("OLD9", variables)  # the newest version's preferences only

    def test_unreadable_preferences_are_ignored(self):
        home = self.t / "cfg"
        (home / "10.0").mkdir(parents=True)
        (home / "10.0" / "kicad_common.json").write_text("{not json", encoding="utf-8")
        (home / "10.0" / "sym-lib-table").write_bytes(b"\xff\xfe(sym_lib_table")
        env = {"KICAD_CONFIG_HOME": str(home)}
        self.assertEqual(libstock.path_variables(env)["KICAD_CONFIG_HOME"], str(home))
        self.assertEqual(libstock.global_lib_table(libstock.config_dirs(env), env), {})


class Defaults(unittest.TestCase):
    def test_default_names_are_kicad_10_libraries(self):
        names = libcfg.DEFAULT_STOCK_SYMBOL_LIBRARIES
        for gone in ("MCU_ST_STM32", "Logic"):
            self.assertNotIn(gone, names)
        for name in ("Device", "power", "74xGxx", "Sensor_Humidity", "Sensor_Optical", "Sensor_Motion", "Jumper",
                     "Diode", "LED", "Mechanical"):
            self.assertIn(name, names)
        self.assertEqual(len(set(names)), len(names))

    def test_default_names_exist_in_the_installed_kicad(self):
        dirs = libstock.symbol_dirs(H.clean_env())
        if not dirs:
            self.skipTest("no KiCad symbols folder on this computer")
        missing = [n for n in libcfg.DEFAULT_STOCK_SYMBOL_LIBRARIES if not (dirs[0] / (n + ".kicad_sym")).is_file()]
        self.assertEqual(missing, [], dirs[0])

    def test_examples_hold_the_default_list(self):
        example = json.loads((H.REPO / "examples" / "kicad-part-importer.json").read_text(encoding="utf-8"))
        self.assertEqual(tuple(example["stock_symbol_libraries"]), libcfg.DEFAULT_STOCK_SYMBOL_LIBRARIES)
        try:
            loads = libcfg._toml_loads()
        except libcfg.ConfigError:
            return
        example = loads((H.REPO / "examples" / "kicad-part-importer.toml").read_text(encoding="utf-8"))
        self.assertEqual(tuple(example["stock_symbol_libraries"]), libcfg.DEFAULT_STOCK_SYMBOL_LIBRARIES)


class MigrateSchematic(Base):
    """--migrate-schematic leaves the parts of KiCad's libraries alone, from what
    it finds on the computer, even when the list does not name them."""

    PARTS = [("OldLib:OLDREG", "OldFp:SOT_DEMO"),                     # custom: migrated
             ("Sensor_Humidity:SHT4x", "Sensor_Humidity:DFN-4"),       # installed in KiCad's symbols folder
             ("74xGxx:SN74LVC1G14DRL", "Package_TO_SOT_SMD:SOT-553"),  # in KiCad's global table
             ("Device:R", "Resistor_SMD:R_0603")]                      # on the list

    def make_project(self, stock_list, sym_entries=()):
        self.project = self.t / "board"
        self.lib = H.make_library(self.project / "lib")
        (self.lib / "kicad-part-importer.json").write_text(
            json.dumps({"stock_symbol_libraries": stock_list}), encoding="utf-8")
        H.write_eol(self.project / "old" / "OldLib.kicad_sym", H.old_symbol_library(("OLDREG", "OldFp:SOT_DEMO")))
        H.write_eol(self.project / "old" / "Sensor_Humidity.kicad_sym", H.old_symbol_library(("SHT4x", "")))
        H.write_eol(self.project / "old" / "OldFp.pretty" / "SOT_DEMO.kicad_mod", H.old_footprint("SOT_DEMO"))
        H.write_eol(self.project / "sym-lib-table",
                    H.lib_table("sym", [("OldLib", "${KIPRJMOD}/old/OldLib.kicad_sym")] + list(sym_entries)))
        H.write_eol(self.project / "fp-lib-table", H.lib_table("fp", [("OldFp", "${KIPRJMOD}/old/OldFp.pretty")]))
        self.sch = H.write_eol(self.project / "board.kicad_sch", H.schematic(self.PARTS))

    def migrate(self, env, stdin="5\n5\n"):
        return H.run_importer("--library", self.lib, "--migrate-schematic", self.sch, stdin=stdin, env_extra=env)

    def test_kicad_libraries_are_left_alone(self):
        self.make_project(["Device"])
        env = H.kicad_env(self.t / "kicad", installed=["Sensor_Humidity"], global_libs=["74xGxx"])
        r = self.migrate(env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Leaving alone the parts from stock libraries: 74xGxx, Device, Sensor_Humidity", r.stdout)
        self.assertIn("Found 1 custom components to consider", r.stdout)
        self.assertNotIn("not found in sym-lib-table", r.stdout)
        sch = lib3d.read_text(self.sch)
        self.assertIn('(lib_id "lib_power_management:OLDREG")', sch)
        for lib_id in ("Sensor_Humidity:SHT4x", "74xGxx:SN74LVC1G14DRL", "Device:R"):
            self.assertIn('(lib_id "%s")' % lib_id, sch)

    def test_without_kicad_the_list_decides(self):
        # No KiCad found: a library off the list is not stock (0.1.0's default
        # left out Sensor_Humidity and 74xGxx, and this is what happened).
        self.make_project(["Device"])
        r = self.migrate(H.kicad_env(self.t / "kicad"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("Leaving alone the parts from stock libraries: Device\n", r.stdout)
        self.assertIn("Symbol library 'Sensor_Humidity' not found in sym-lib-table; skipped", r.stdout)
        # The default list names KiCad 10's most used libraries.
        self.make_project_default()
        r = self.migrate(H.kicad_env(self.t / "kicad"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Leaving alone the parts from stock libraries: 74xGxx, Device, Sensor_Humidity", r.stdout)

    def make_project_default(self):
        self.tmp.cleanup()
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.make_project([])
        (self.lib / "kicad-part-importer.json").unlink()

    def test_a_project_library_named_like_a_kicad_one_is_migrated(self):
        self.make_project([], sym_entries=[("Sensor_Humidity", "${KIPRJMOD}/old/Sensor_Humidity.kicad_sym")])
        env = H.kicad_env(self.t / "kicad", installed=["Sensor_Humidity", "Device"], global_libs=["74xGxx"])
        r = self.migrate(env, stdin="5\n9\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Leaving alone the parts from stock libraries: 74xGxx, Device\n", r.stdout)
        self.assertIn("Component: Sensor_Humidity:SHT4x", r.stdout)
        sch = lib3d.read_text(self.sch)
        self.assertIn('(lib_id "lib_sensors:SHT4x")', sch)
        self.assertIn('(symbol "SHT4x"', lib3d.read_text(self.lib / "lib_sym" / "lib_sensors.kicad_sym"))


if __name__ == "__main__":
    unittest.main()
