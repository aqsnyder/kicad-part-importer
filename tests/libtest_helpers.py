"""Shared fixtures for the kicad-part-importer tests: a scratch library with the
default layout, and small synthetic vendor-style zips (TI / Ultra Librarian,
SamacSys and SnapEDA layouts). Every fixture is generated here; no vendor
files are used."""
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMPORTER = REPO / "kicad_part_importer.py"
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True

# The default categories and library name prefix (see kicad_lib_config).
CATEGORIES = ["connectors", "passives", "semiconductors_discretes", "ics_general", "power_management",
              "mcus_soc", "memory_storage", "rf_communication", "sensors", "optoelectronics_displays",
              "electromechanical", "protection", "mechanicals_misc"]
PREFIX = "lib_"

EMPTY_LIB = "(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)\n)"

SYMBOL = """(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)
  (symbol "{name}" (pin_names (offset 0.254)) (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 2.54 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Value" "{name}" (id 1) (at 0 0 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Footprint" "{fp}" (id 2) (at 0 0 0)
      (effects (font (size 1.27 1.27)) hide)
    )
    (symbol "{name}_0_1"
      (rectangle (start -2.54 2.54) (end 2.54 -2.54)
        (stroke (width 0) (type default) (color 0 0 0 0))
        (fill (type none))
      )
    )
  )
)
"""

# KiCad 6 footprint as Ultra Librarian / TI ship it: no (model ...) line.
FP_UL = """(footprint "{declared}" (version 20211014) (generator pcbnew)
  (layer "F.Cu")
  (attr smd)
  (fp_text reference "REF**" (at 0 -2) (layer "F.SilkS")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_text value "{declared}" (at 0 2) (layer "F.Fab")
    (effects (font (size 1 1) (thickness 0.15)))
  )
  (fp_line (start -1.5 -1) (end 1.5 -1) (layer "F.CrtYd") (width 0.05))
  (pad "1" smd rect (at -0.6 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))
  (pad "2" smd rect (at 0.6 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""

# KiCad 5 (module ...) footprint as SamacSys ships it: bare, unquoted model name.
FP_SAMACSYS = """(module "{name}" (layer F.Cu)
  (descr "test")
  (fp_text reference REF** (at 0 0) (layer F.SilkS)
    (effects (font (size 1.27 1.27) (thickness 0.254)))
  )
  (fp_text value {name} (at 0 0) (layer F.SilkS) hide
    (effects (font (size 1.27 1.27) (thickness 0.254)))
  )
  (fp_line (start -2 -1) (end 2 -1) (layer F.CrtYd) (width 0.05))
  (pad 1 smd rect (at -1 0) (size 1 1) (layers F.Cu F.Paste F.Mask))
  (pad 2 smd rect (at 1 0) (size 1 1) (layers F.Cu F.Paste F.Mask))
  (model {model}
    (at (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))
  )
)
"""

# KiCad 6 footprint as SnapEDA ships it: unquoted name, no (model ...) line.
FP_SNAPEDA = """(footprint {name} (layer F.Cu) (tedit 00000000)
  (descr "")
  (attr smd)
  (fp_text reference REF** (at 0 -2) (layer F.SilkS)
    (effects (font (size 0.64 0.64) (thickness 0.15)))
  )
  (fp_text value {name} (at 0 2) (layer F.Fab)
    (effects (font (size 0.64 0.64) (thickness 0.15)))
  )
  (pad 1 smd rect (at -0.5 0) (size 0.4 0.4) (layers F.Cu F.Mask F.Paste))
  (pad 2 smd rect (at 0.5 0) (size 0.4 0.4) (layers F.Cu F.Mask F.Paste))
)
"""

FAKE_STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

# A 2 x 1 mm board with nothing on it: kicad-cli exports it as a valid STEP
# body, which the KiCad tests use as a model file.
BOX_PCB = """(kicad_pcb (version 20240108) (generator "pcbnew") (generator_version "8.0")
  (general (thickness 1.6) (legacy_teardrops no))
  (paper "A4")
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (44 "Edge.Cuts" user)
  )
  (setup (pad_to_mask_clearance 0))
  (net 0 "")
  (gr_rect (start 0 0) (end 2 1) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))
)
"""


def crlf(text):
    return text.replace("\n", "\r\n")


def make_library(root, eol="\n", prefix=PREFIX, categories=None, symbol_dir="lib_sym", footprint_dir="lib_fp",
                 model_dir="3d_models"):
    """Empty category libraries, .pretty folders and the model folder under root."""
    root = Path(root)
    (root / symbol_dir).mkdir(parents=True, exist_ok=True)
    (root / model_dir).mkdir(parents=True, exist_ok=True)
    for c in (CATEGORIES if categories is None else categories):
        (root / footprint_dir / ("%s%s.pretty" % (prefix, c))).mkdir(parents=True, exist_ok=True)
        with open(root / symbol_dir / ("%s%s.kicad_sym" % (prefix, c)), "w", newline="") as fh:
            fh.write(EMPTY_LIB.replace("\n", eol))
    return root


def ti_zip(path, part="TESTSW1", pkg="PKG0005A", step=FAKE_STEP, variants=("IPC_A", "IPC_B", "MFG")):
    """TI / Ultra Librarian layout: <pkg>.stp at the root, KiCADv6/<stamp>.kicad_sym,
    KiCADv6/footprints.pretty/<pkg>-<variant>.kicad_mod (all declaring the first
    variant's name, as TI's do), CRLF line ends."""
    names = ["%s-%s" % (pkg, v) for v in variants]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(pkg + ".stp", step)
        z.writestr("KiCADv6/2026-01-01_12-00-00.kicad_sym", crlf(SYMBOL.format(name=part, fp=names[0])))
        for n in names:
            z.writestr("KiCADv6/footprints.pretty/%s.kicad_mod" % n, crlf(FP_UL.format(declared=names[0])))
    return names


def samacsys_zip(path, part="TESTTVS", fp="DIONTEST", step=FAKE_STEP):
    """SamacSys layout: <PN>/KiCad/<PN>.kicad_sym + <fp>.kicad_mod (KiCad 5, bare
    model name), <PN>/3D/<PN>.stp, plus files for other CAD tools."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("%s/KiCad/%s.kicad_sym" % (part, part), crlf(SYMBOL.format(name=part, fp=fp)))
        z.writestr("%s/KiCad/%s.kicad_mod" % (part, fp), crlf(FP_SAMACSYS.format(name=fp, model=part + ".stp")))
        z.writestr("%s/KiCad/%s.lib" % (part, part), "EESchema-LIBRARY Version 2.3\n")
        z.writestr("%s/3D/%s.stp" % (part, part), step)
        z.writestr("%s/Altium/%s.SchLib" % (part, part), b"\x00")
        z.writestr("license.txt", "terms\n")


def snapeda_zip(path, part="TESTREG1-7"):
    """SnapEDA layout: <PN>.kicad_sym whose Footprint field names a library called
    after the part (<PN>:IC_<PN>), IC_<PN>.kicad_mod without a model, and a
    how-to page and a license; no 3D model."""
    fp = "IC_" + part
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(part + ".kicad_sym", SYMBOL.format(name=part, fp=part + ":" + fp))
        z.writestr(fp + ".kicad_mod", FP_SNAPEDA.format(name=fp))
        z.writestr("how-to-import.htm", "<html><body>How to import</body></html>\n")
        z.writestr("License.txt", "terms\n")
    return fp


def _kicad_path_var(name):
    """KiCad's settings folder and symbol folder variables (see kicad_lib_stock)."""
    n = name.upper()
    return n == "KICAD_CONFIG_HOME" or (n.startswith("KICAD") and n.endswith("_SYMBOL_DIR"))


def clean_env(env_extra=None):
    """This process's environment without kicad-part-importer settings or KiCad's
    settings / symbol folder variables, so a developer's own variables cannot
    change a test."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("KICAD_PART_IMPORTER_") and not _kicad_path_var(k)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("PYTHONIOENCODING", None)
    if env_extra:
        env.update(env_extra)
    return env


def run_importer(*args, stdin=None, env_extra=None, isolated=True, cwd=None):
    """Run kicad_part_importer.py in a subprocess; returns CompletedProcess (text)."""
    cmd = [sys.executable, "-B"] + (["-I"] if isolated else []) + [str(IMPORTER)] + [str(a) for a in args]
    return subprocess.run(cmd, input=stdin, capture_output=True, env=clean_env(env_extra), cwd=cwd,
                          text=True, encoding="utf-8", errors="replace", timeout=600)


def snapshot(root):
    """{relative path: bytes} for every file under root."""
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def make_step_with_kicad(kicad_cli, out_path):
    """Export BOX_PCB to a STEP file with kicad-cli; return its bytes."""
    with tempfile.TemporaryDirectory(prefix="kpi_box_") as d:
        pcb = os.path.join(d, "box.kicad_pcb")
        with open(pcb, "w") as fh:
            fh.write(BOX_PCB)
        subprocess.run([kicad_cli, "pcb", "export", "step", "-f", "-o", str(out_path), pcb],
                       check=True, capture_output=True, timeout=300)
    return Path(out_path).read_bytes()


def write_eol(path, text, eol="\n"):
    """Write text (written with LF) to path with the given line ending, no translation."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace("\n", eol))
    return Path(path)


# ----------------------------------------------------------------- migration
# Tab-indented, as KiCad 7+ writes them (the migration commands need tabs).

OLD_SYMBOL = (
    '\t(symbol "{name}"\n'
    '\t\t(pin_names\n\t\t\t(offset 0.254)\n\t\t)\n'
    '\t\t(property "Reference" "U"\n\t\t\t(at 0 2.54 0)\n\t\t)\n'
    '\t\t(property "Value" "{name}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
    '\t\t(property "Footprint" "{fp}"\n\t\t\t(at 0 0 0)\n\t\t)\n'
    '\t\t(property "Datasheet" "https://example.com/{name}.pdf"\n\t\t\t(at 0 0 0)\n\t\t)\n'
    '\t\t(symbol "{name}_0_1"\n'
    '\t\t\t(rectangle\n\t\t\t\t(start -2.54 2.54)\n\t\t\t\t(end 2.54 -2.54)\n\t\t\t)\n'
    '\t\t)\n'
    '\t\t(symbol "{name}_1_1"\n'
    '\t\t\t(pin passive line\n\t\t\t\t(at -5.08 0 0)\n\t\t\t\t(length 2.54)\n\t\t\t)\n'
    '\t\t)\n'
    '\t)\n'
)


def old_symbol_library(*symbols):
    """A tab-indented symbol library holding OLD_SYMBOL blocks for (name, footprint field) pairs."""
    body = "".join(OLD_SYMBOL.format(name=n, fp=fp) for n, fp in symbols)
    return '(kicad_symbol_lib\n\t(version 20231120)\n\t(generator "kicad_symbol_editor")\n' + body + ')\n'


def old_footprint(name, marker="original"):
    """A small tab-indented footprint; marker tells two same-named copies apart."""
    return ('(footprint "%s"\n\t(version 20240108)\n\t(generator "pcbnew")\n\t(layer "F.Cu")\n'
            '\t(descr "%s")\n\t(pad "1" smd rect\n\t\t(at 0 0)\n\t\t(size 1 1)\n\t\t(layers "F.Cu")\n\t)\n)\n'
            % (name, marker))


SCHEMATIC_HEAD = ('(kicad_sch\n\t(version 20231120)\n\t(generator "eeschema")\n'
                  '\t(uuid "00000000-0000-0000-0000-000000000001")\n\t(paper "A4")\n')


def schematic(parts, embedded_footprints=False):
    """A tab-indented schematic placing one instance of each (lib_id, footprint field).
    With embedded_footprints, each lib_symbols entry carries the Footprint field
    too, as KiCad's copies of the library symbols do."""
    out = [SCHEMATIC_HEAD, "\t(lib_symbols\n"]
    for lib_id, fp in parts:
        field = '\t\t\t(property "Footprint" "%s"\n\t\t\t\t(at 0 0 0)\n\t\t\t)\n' % fp if embedded_footprints else ""
        out.append('\t\t(symbol "%s"\n\t\t\t(property "Reference" "U"\n\t\t\t\t(at 0 0 0)\n\t\t\t)\n%s\t\t)\n'
                   % (lib_id, field))
    out.append("\t)\n")
    for i, (lib_id, fp) in enumerate(parts, 1):
        out.append('\t(symbol\n\t\t(lib_id "%s")\n\t\t(at %d 50 0)\n'
                   '\t\t(property "Reference" "U%d"\n\t\t\t(at 0 0 0)\n\t\t)\n'
                   '\t\t(property "Footprint" "%s"\n\t\t\t(at 0 0 0)\n\t\t)\n\t)\n' % (lib_id, 20 * i, i, fp))
    out.append(")\n")
    return "".join(out)


def lib_table(kind, entries):
    """A sym-lib-table / fp-lib-table text with (name, uri) or (name, uri, type)
    entries (type "KiCad" by default)."""
    head = "sym_lib_table" if kind == "sym" else "fp_lib_table"
    rows = "".join('  (lib (name "%s")(type "%s")(uri "%s")(options "")(descr ""))\n'
                   % (e[0], e[2] if len(e) > 2 else "KiCad", e[1]) for e in entries)
    return "(%s\n  (version 7)\n%s)\n" % (head, rows)


def kicad_env(root, installed=(), global_libs=(), version="10.0"):
    """A made-up KiCad under root, for kicad_lib_stock: a symbols folder holding
    <name>.kicad_sym for each installed name, and a settings folder whose
    <version>/sym-lib-table nests a default table (as KiCad 10 writes it) that
    lists global_libs as ${KICAD10_SYMBOL_DIR}/<name>.kicad_sym. Returns the
    variables that point the tool at it; with nothing installed they hide any
    real KiCad."""
    root = Path(root)
    symbols = root / "kicad_symbols"
    symbols.mkdir(parents=True, exist_ok=True)
    for name in installed:
        write_eol(symbols / (name + ".kicad_sym"), EMPTY_LIB)
    config = root / "kicad_config"
    (config / version).mkdir(parents=True, exist_ok=True)
    if global_libs:
        template = write_eol(root / "kicad_template" / "sym-lib-table",
                             lib_table("sym", [(n, "${KICAD10_SYMBOL_DIR}/%s.kicad_sym" % n) for n in global_libs]))
        write_eol(config / version / "sym-lib-table", lib_table("sym", [("KiCad", template.as_posix(), "Table")]))
    return {"KICAD_CONFIG_HOME": str(config), "KICAD10_SYMBOL_DIR": str(symbols)}


# --------------------------------------------------------------------- git

GIT_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "kpi-test", "GIT_COMMITTER_NAME": "Test",
           "GIT_COMMITTER_EMAIL": "kpi-test", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    """Run git in cwd with a neutral identity and configuration; return its stdout."""
    return subprocess.run(["git"] + [str(a) for a in args], cwd=cwd, env=clean_env(GIT_ENV), check=True,
                          capture_output=True, text=True).stdout
