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


def clean_env(env_extra=None):
    """This process's environment without kicad-part-importer settings, so a
    developer's own KICAD_PART_IMPORTER_* variables cannot change a test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("KICAD_PART_IMPORTER_")}
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
