"""--migrate, --migrate-schematic and --init-libraries on scratch libraries and
projects (subprocess, no KiCad needed): what gets copied, what the schematic is
pointed at, and that files keep their line endings on every OS."""
import re
import tempfile
import unittest
from pathlib import Path

import libtest_helpers as H
import kicad_lib_3d as lib3d


def crlf_free(path):
    return b"\r" not in Path(path).read_bytes()


def all_crlf(path):
    raw = Path(path).read_bytes()
    return raw.count(b"\n") == raw.count(b"\r\n") > 0


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class MigrateSymbols(Base):
    """--migrate FILE / --migrate: one menu per symbol, the footprint it names comes along."""

    def setUp(self):
        super().setUp()
        self.lib = H.make_library(self.t / "partlib")
        self.old = H.write_eol(self.lib / "lib_sym" / "old_parts.kicad_sym",
                               H.old_symbol_library(("OLDREG", "old_footprints:SOT_DEMO")))
        self.fp = H.write_eol(self.lib / "lib_fp" / "old_footprints.pretty" / "SOT_DEMO.kicad_mod",
                              H.old_footprint("SOT_DEMO", "the one the field names"))
        # A footprint of the same name in another library: the field's library wins.
        H.write_eol(self.lib / "lib_fp" / "a_decoy.pretty" / "SOT_DEMO.kicad_mod", H.old_footprint("SOT_DEMO", "decoy"))
        self.target = self.lib / "lib_sym" / "lib_power_management.kicad_sym"
        self.target_fp = self.lib / "lib_fp" / "lib_power_management.pretty" / "SOT_DEMO.kicad_mod"

    def migrate(self, *args, stdin="5\n"):
        return H.run_importer("--library", self.lib, "--migrate", *args, stdin=stdin)

    def test_symbol_name_footprint_and_wording(self):
        r = self.migrate(self.old)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Component: OLDREG\n", r.stdout)  # not the unit sub-symbol OLDREG_1_1
        self.assertIn("Added OLDREG to power_management", r.stdout)
        self.assertNotIn("OLDREG_1_1 to", r.stdout)
        self.assertEqual(lib3d.read_text(self.target).count('(symbol "OLDREG"'), 1)
        # The footprint "old_footprints:SOT_DEMO" names is found and copied, not moved.
        self.assertEqual(self.target_fp.read_bytes(), self.fp.read_bytes())
        self.assertTrue(self.fp.is_file())
        self.assertIn("Copied footprint SOT_DEMO to power_management", r.stdout)
        self.assertNotIn("Moved", r.stdout)
        self.assertNotIn("not found", r.stdout)

    def test_running_again_does_not_duplicate_the_symbol(self):
        self.assertEqual(self.migrate(self.old).returncode, 0)
        before = H.snapshot(self.lib)
        r = self.migrate(self.old)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # the symbol was not migrated this time
        self.assertIn("OLDREG already exists in lib_power_management", r.stdout)
        self.assertEqual(lib3d.read_text(self.target).count('(symbol "OLDREG"'), 1)
        self.assertEqual(H.snapshot(self.lib), before)
        # Every other .kicad_sym in the symbol folder: the same.
        r = self.migrate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(lib3d.read_text(self.target).count('(symbol "OLDREG"'), 1)

    def test_skipping_is_not_a_failure(self):
        r = self.migrate(self.old, stdin="0\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Skipping OLDREG", r.stdout)
        self.assertNotIn("OLDREG", lib3d.read_text(self.target))

    def test_a_stock_footprint_is_left_alone(self):
        old = H.write_eol(self.t / "stock.kicad_sym", H.old_symbol_library(("R1K", "Resistor_SMD:R_0603")))
        r = self.migrate(old)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Footprint Resistor_SMD:R_0603 not found", r.stdout)
        self.assertIn('(symbol "R1K"', lib3d.read_text(self.target))


class MigrateSchematic(Base):
    """--migrate-schematic: only parts whose symbol was copied are pointed at the
    category library; a footprint that was not copied keeps its Footprint field."""

    PARTS = [("OldLib:OLDREG", "OldFp:SOT_DEMO"),   # in the tables, symbol and footprint present
             ("Ghost:GHOST1", "OldFp:GHOSTFP"),     # symbol library not in sym-lib-table
             ("OldLib:OLDREG2", "OldFp:NOPE"),      # footprint library listed, footprint missing
             ("Device:R", "Resistor_SMD:R_0603")]   # stock: left alone

    def make_project(self, eol="\n", parts=None, symbols=(("OLDREG", "OldFp:SOT_DEMO"), ("OLDREG2", "OldFp:NOPE")),
                     embedded_footprints=False):
        self.project = self.t / "board"
        self.lib = H.make_library(self.project / "lib")
        H.write_eol(self.project / "old" / "OldLib.kicad_sym", H.old_symbol_library(*symbols), eol)
        self.fp = H.write_eol(self.project / "old" / "OldFp.pretty" / "SOT_DEMO.kicad_mod",
                              H.old_footprint("SOT_DEMO"), eol)
        H.write_eol(self.project / "sym-lib-table",
                    H.lib_table("sym", [("OldLib", "${KIPRJMOD}/old/OldLib.kicad_sym")]), eol)
        H.write_eol(self.project / "fp-lib-table", H.lib_table("fp", [("OldFp", "${KIPRJMOD}/old/OldFp.pretty")]), eol)
        self.sch = H.write_eol(self.project / "board.kicad_sch",
                               H.schematic(self.PARTS if parts is None else parts, embedded_footprints), eol)

    def migrate(self, stdin="5\n5\n5\n5\n"):
        return H.run_importer("--library", self.lib, "--migrate-schematic", self.sch, stdin=stdin)

    def test_only_copied_parts_are_rewritten(self):
        self.make_project()
        r = self.migrate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # GHOST1 and the NOPE footprint were not migrated
        sch = lib3d.read_text(self.sch)
        # Copied: lib_id and lib_symbols entry point at the category library, footprint too.
        self.assertIn('(lib_id "lib_power_management:OLDREG")', sch)
        self.assertIn('(symbol "lib_power_management:OLDREG"', sch)
        self.assertIn('"Footprint" "lib_power_management:SOT_DEMO"', sch)
        # Not in sym-lib-table: no menu, nothing written, references kept.
        self.assertIn("Symbol library 'Ghost' not found in sym-lib-table; skipped", r.stdout)
        self.assertNotIn("Component: GHOST1", r.stdout)
        self.assertIn('(lib_id "Ghost:GHOST1")', sch)
        self.assertIn('(symbol "Ghost:GHOST1"', sch)
        # Symbol copied, footprint not found: the Footprint field is kept.
        self.assertIn('(lib_id "lib_power_management:OLDREG2")', sch)
        self.assertIn('"Footprint" "OldFp:NOPE"', sch)
        self.assertIn('(lib_id "Device:R")', sch)
        lib_sym = lib3d.read_text(self.lib / "lib_sym" / "lib_power_management.kicad_sym")
        self.assertEqual([lib_sym.count('(symbol "%s"' % n) for n in ("OLDREG", "OLDREG2", "GHOST1")], [1, 1, 0])
        self.assertIn("Migrated 2 component(s)", r.stdout)

    def test_a_symbol_already_in_the_category_is_not_copied_or_rewritten(self):
        self.make_project()
        target = self.lib / "lib_sym" / "lib_power_management.kicad_sym"
        H.write_eol(target, H.old_symbol_library(("OLDREG", "lib_power_management:OTHER")))
        r = self.migrate()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("OLDREG already exists in lib_power_management", r.stdout)
        self.assertEqual(lib3d.read_text(target).count('(symbol "OLDREG"'), 1)
        self.assertIn('(lib_id "OldLib:OLDREG")', lib3d.read_text(self.sch))

    def test_a_part_left_alone_keeps_a_footprint_it_shares(self):
        # GHOST1 (its library is not in sym-lib-table) and OLDREG2 (the category
        # already has it) use the footprint OLDREG uses. Only OLDREG, placed and in
        # lib_symbols, is pointed at the copied footprint.
        parts = [("OldLib:OLDREG", "OldFp:SOT_DEMO"), ("Ghost:GHOST1", "OldFp:SOT_DEMO"),
                 ("OldLib:OLDREG2", "OldFp:SOT_DEMO")]
        self.make_project(parts=parts, symbols=(("OLDREG", "OldFp:SOT_DEMO"), ("OLDREG2", "OldFp:SOT_DEMO")),
                          embedded_footprints=True)
        H.write_eol(self.lib / "lib_sym" / "lib_power_management.kicad_sym",
                    H.old_symbol_library(("OLDREG2", "lib_power_management:SOT_DEMO")))
        r = self.migrate(stdin="5\n5\n")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # GHOST1 and OLDREG2 were not migrated
        self.assertIn("Migrated 1 component(s)", r.stdout)
        sch = lib3d.read_text(self.sch)
        placed = dict(re.findall(r'\t\(symbol\n\t\t\(lib_id "([^"]+)"\).*?\(property "Footprint" "([^"]*)"', sch, re.S))
        embedded = dict(re.findall(r'\t\t\(symbol "([^"]+)"\n.*?\(property "Footprint" "([^"]*)"', sch, re.S))
        expected = {"lib_power_management:OLDREG": "lib_power_management:SOT_DEMO",
                    "Ghost:GHOST1": "OldFp:SOT_DEMO", "OldLib:OLDREG2": "OldFp:SOT_DEMO"}
        self.assertEqual(placed, expected)
        self.assertEqual(embedded, expected)
        self.assertTrue((self.lib / "lib_fp" / "lib_power_management.pretty" / "SOT_DEMO.kicad_mod").is_file())

    def test_line_endings_are_kept(self):
        for eol in ("\n", "\r\n"):
            with self.subTest(eol=repr(eol)):
                self.make_project(eol)
                r = self.migrate()
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                fp = self.lib / "lib_fp" / "lib_power_management.pretty" / "SOT_DEMO.kicad_mod"
                self.assertIn('(lib_id "lib_power_management:OLDREG")', lib3d.read_text(self.sch))
                if eol == "\n":
                    self.assertTrue(crlf_free(self.sch))
                    self.assertTrue(crlf_free(fp))
                else:
                    self.assertTrue(all_crlf(self.sch))
                    self.assertTrue(all_crlf(fp))
                self.assertEqual(fp.read_bytes(), self.fp.read_bytes())  # the footprint, byte for byte
                self.assertEqual((self.project / "board.kicad_sch.bak").read_bytes(),
                                 H.schematic(self.PARTS).replace("\n", eol).encode("utf-8"))
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                self.t = Path(self.tmp.name)


class SchematicBlocks(unittest.TestCase):
    """The blocks a schematic update may change a Footprint field in: placed
    symbols by lib_id, and lib_symbols entries; parentheses in strings do not count."""

    def test_placed_and_embedded_symbols(self):
        import kicad_part_importer as kpi
        sch = ('(kicad_sch (version 20211123) (generator eeschema)\n'
               '  (lib_symbols\n'
               '    (symbol "A:X" (property "Footprint" "F:P") (symbol "X_0_1" (rectangle)))\n'
               '  )\n'
               '  (text "a (symbol (lib_id \\"A:Y\\")) in a note" (at 0 0 0))\n'
               '  (symbol (lib_id "A:X") (at 10 10 0) (property "Value" "1 (x)") (property "Footprint" "F:P"))\n'
               '  (sheet (at 0 0) (property "Sheetname" "s"))\n'
               ')\n')
        blocks = [(sch[s:e], lib_id) for s, e, lib_id in kpi._schematic_symbol_blocks(sch)]
        self.assertEqual(blocks, [
            ('(symbol "A:X" (property "Footprint" "F:P") (symbol "X_0_1" (rectangle)))', "A:X"),
            ('(symbol (lib_id "A:X") (at 10 10 0) (property "Value" "1 (x)") (property "Footprint" "F:P"))', "A:X")])


class InitLineEndings(Base):
    def test_new_symbol_libraries_are_lf(self):
        lib = self.t / "lib"
        r = H.run_importer("--init", "--library", lib)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        libs = sorted((lib / "lib_sym").glob("*.kicad_sym"))
        self.assertEqual(len(libs), 13)
        self.assertTrue(all(crlf_free(p) for p in libs))
        self.assertEqual(libs[0].read_bytes().decode("utf-8"), H.EMPTY_LIB)


if __name__ == "__main__":
    unittest.main()
