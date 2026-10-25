# 3D models

A footprint shows a 3D body in KiCad's 3D viewer and in STEP exports only
when its `(model ...)` path resolves to a model file. Vendor footprints
mostly do not resolve once they sit in a shared library:

- TI / Ultra Librarian and SnapEDA footprints have no `(model ...)` at all.
- SamacSys footprints name the model by a bare file name. KiCad resolves a
  bare name against the project folder, where the file is not.
- Older libraries carry absolute paths from somebody's machine, paths through
  a path variable nobody defines any more, or names in the wrong letter case.
  The last kind loads on Windows and macOS and fails on Linux.

The tool fixes this with one rule: every model lives in the library's model
folder, and every footprint names it as `<library_mount>/<model_dir>/<file>`
(by default `${KIPRJMOD}/<library folder>/3d_models/<file>`). That path
resolves in any project that mounts the library the same way, on any
machine and any operating system.

| Option | What it does |
|---|---|
| `--link-3d` | While importing: point each footprint at the library's copy of its model |
| `--check-3d` | Classify every model path in the library; exit 1 while problems remain |
| `--fix-3d` | With `--check-3d`: rewrite the fixable paths |
| `--verify-3d` | Load the footprints in KiCad and report every model that does not load |

## Linking while importing: `--link-3d`

An Ultra Librarian footprint before import (the zip unpacked into
`/tmp/demo/x`), then after `--link-3d`. A model block was inserted with zero
offset and rotation and unit scale:

```text
$ grep -c "(model" /tmp/demo/x/KiCADv6/footprints.pretty/PKG0006A-MFG.kicad_mod
0

$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --yes
Plan: ul_DEMOBUCK1.zip -> power_management (lib_power_management)
  ...
  footprint  PKG0006A-MFG           add       lib_fp/lib_power_management.pretty/PKG0006A-MFG.kicad_mod
             model: insert ${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp (only model)
  3D model   PKG0006A.stp           add       3d_models/PKG0006A.stp
...
✓ Added 3D model PKG0006A.stp

$ tail -n 7 lib_fp/lib_power_management.pretty/PKG0006A-MFG.kicad_mod
  (pad "2" smd rect (at 0.6 0) (size 0.5 0.5) (layers "F.Cu" "F.Paste" "F.Mask"))
  (model "${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))
  )
)
```

A SamacSys footprint before and after. Only the path changed; the placement
SamacSys set is kept:

```text
$ grep -A3 "(model" /tmp/demo/x/DEMOTVS5/KiCad/SOD_DEMO.kicad_mod
  (model DEMOTVS5.stp
    (at (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))

$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --yes
...
             model: rewrite DEMOTVS5.stp -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp (named by footprint)
...

$ grep -A3 "(model" lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod
  (model "${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp"
    (at (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))
```

The edits are text edits: only the path token changes (the KiCad 5 `(at ...)`
keyword stays until KiCad next saves the footprint), and line endings are
kept.

Which model goes with which footprint is decided by the rules in
[vendor-formats.md](vendor-formats.md#how-a-footprint-gets-its-model). A
model already in the model folder with the same bytes is reused, not copied
again. One with the same name and other bytes is refused unless you pass
`--overwrite`.

## Checking the library: `--check-3d`

`--check-3d` reads every footprint in the category footprint libraries
(`<footprint_dir>/<library_prefix>*.pretty` plus the library of any category
whose `name` lacks the prefix, or every `.pretty` with
`--all-footprint-libs`) and classifies each `(model ...)` path:

| Kind | Meaning | Fixable |
|---|---|---|
| `ok` | Library form, and the file exists with exactly that spelling, folders included | (nothing to fix) |
| `case` | Library form, but the letter case of the file name or of a folder in the path differs (`3D_Models/X.step` for `3d_models/X.step`). Loads on Windows and macOS, not on Linux | yes: the real spelling |
| `missing` | Library form, no such file | no |
| `bare` | A file name only; KiCad looks next to the project file | yes, if the file is in the model folder or a `model_search_dirs` folder |
| `absolute` | `/...`, `X:/...` or `\\server\...`: machine-specific | same |
| `other-var` | Another `${VAR}/...` path, or a relative path with folders | same |
| `stock` | `${KICADn_3DMODEL_DIR}/...`, KiCad's own models | not checked |
| `none` | The footprint has no `(model ...)` (counted, not a problem) | - |

A library with one footprint of each kind (and four linked ones):

```text
$ kicad-part-importer --check-3d
Footprints checked: 9; model references: absolute 1, case 1, missing 1, ok 4, other-var 1, stock 1
  absolute  lib_fp/lib_ics_general.pretty/ABS_PATH.kicad_mod: /opt/kicad-models/OLDPART.step  -> ${KIPRJMOD}/my_kicad_library/3d_models/OLDPART.step
  case      lib_fp/lib_ics_general.pretty/CASE_ONLY.kicad_mod: ${KIPRJMOD}/my_kicad_library/3d_models/casepart.STEP  -> ${KIPRJMOD}/my_kicad_library/3d_models/CASEPART.step
  missing   lib_fp/lib_ics_general.pretty/GONE.kicad_mod: ${KIPRJMOD}/my_kicad_library/3d_models/GONE.step
  other-var lib_fp/lib_ics_general.pretty/OTHER_VAR.kicad_mod: ${OLD_LIB_DIR}/packages3d/OLDPART.step  -> ${KIPRJMOD}/my_kicad_library/3d_models/OLDPART.step
```

Exit code 1: problems remain. The arrow shows the fix `--fix-3d` would make.
`missing` has no arrow because there is no file to point at.

## Fixing: `--fix-3d`

Preview with `--dry-run`, then apply:

```text
$ kicad-part-importer --check-3d --fix-3d --dry-run
Footprints checked: 9; model references: absolute 1, case 1, missing 1, ok 4, other-var 1, stock 1
  ...
Would change 3 footprint file(s): 3 path(s) rewritten, 0 dead duplicate reference(s) removed

$ kicad-part-importer --check-3d --fix-3d --yes
Footprints checked: 9; model references: absolute 1, case 1, missing 1, ok 4, other-var 1, stock 1
  ...
Changed 3 footprint file(s): 3 path(s) rewritten, 0 dead duplicate reference(s) removed
```

The model lines of the five test footprints, after the fix:

```text
$ grep -h "(model" lib_fp/lib_ics_general.pretty/*.kicad_mod
  (model "${KIPRJMOD}/my_kicad_library/3d_models/OLDPART.step"
  (model "${KIPRJMOD}/my_kicad_library/3d_models/CASEPART.step"
  (model "${KIPRJMOD}/my_kicad_library/3d_models/GONE.step"
  (model "${KIPRJMOD}/my_kicad_library/3d_models/OLDPART.step"
  (model "${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0603_1608Metric.step"
```

`GONE.step` is still missing; get the model and copy it into `3d_models/`.
With `--fix-3d`, the exit code is 1 while unfixable problems remain, and with
`--fix-3d --dry-run` it is computed as if the fixes had been made.

**Dead duplicates.** A footprint sometimes carries two `(model ...)` blocks
for the same part, for example a dead bare name next to a working library
path. Rewriting the dead one would stack two coincident bodies in the 3D
view and in STEP exports. When the fix would duplicate a path the footprint
already names, `--fix-3d` removes the dead block instead and counts it as a
"dead duplicate reference removed".

### Machine-readable output

```text
$ kicad-part-importer --check-3d --json 2>/dev/null
{
 "library_root": "/tmp/demo/kicad/my_board/my_kicad_library",
 "footprints": 9,
 "counts": {
  "ok": 7,
  "missing": 1,
  "stock": 1
 },
 "problems": [
  {
   "footprint": "lib_fp/lib_ics_general.pretty/GONE.kicad_mod",
   "ref": "${KIPRJMOD}/my_kicad_library/3d_models/GONE.step",
   "kind": "missing",
   "fix": null,
   "fix_action": null
  }
 ],
 "fixable": [],
 "unfixable": [
  {
   "footprint": "lib_fp/lib_ics_general.pretty/GONE.kicad_mod",
   "ref": "${KIPRJMOD}/my_kicad_library/3d_models/GONE.step",
   "kind": "missing",
   "fix": null,
   "fix_action": null
  }
 ],
 "command": "check-3d",
 "dry_run": false,
 "exit_code": 1,
 "ok": false
}
```

## Proving it in KiCad: `--verify-3d`

A path check cannot tell whether KiCad can actually read the file. A file can
be truncated, or be an HTML error page saved as `.step`. `--verify-3d` asks
KiCad itself:

1. It loads every footprint it checks with KiCad's `pcbnew` module and places
   them on one throwaway board.
2. It lays out a scratch project the way your projects mount the library, so
   `${KIPRJMOD}/...` (or your `${VAR}`) resolves exactly as it would for real.
   Any other path form is left as it is and fails exactly as it would in a
   real project.
3. It runs `kicad-cli pcb export step` and reads KiCad's messages for every
   model that did not load.

It works with an import (it checks the footprints the import wrote; with
`--dry-run`, staged copies of them) and with `--check-3d` (every checked
footprint). KiCad is located before anything is written, so a missing KiCad
never leaves a half-done import.

Output from KiCad 10.0.7 on Windows. First, the SamacSys part imported
**without** `--link-3d`; KiCad cannot find the bare file name:

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --verify-3d --yes
Plan: LIB_DEMOTVS5.zip -> protection (lib_protection)
  symbol     DEMOTVS5               append    lib_sym/lib_protection.kicad_sym
  footprint  SOD_DEMO               add       lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod
  3D model   DEMOTVS5.stp           add       3d_models/DEMOTVS5.stp
  ignored    DEMOTVS5/Altium/DEMOTVS5.SchLib, DEMOTVS5/KiCad/DEMOTVS5.lib, license.txt
⚠ symbol DEMOTVS5: Footprint field 'SOD_DEMO' has no library prefix (KiCad needs lib_protection:SOD_DEMO)
✓ Added symbol(s) from DEMOTVS5.kicad_sym to protection
✓ Added footprint SOD_DEMO.kicad_mod to protection
✓ Added 3D model DEMOTVS5.stp
✗ 3D model did not load: SOD_DEMO.kicad_mod: File not found: DEMOTVS5.stp
3D check: 0 loaded, 1 with a model that did not load (1 of them with no 3D body, 0 with a dead extra reference next to one that loads), 0 without a model (KiCad 10.0.7)
```

Exit code 1. The library check sees it, fixes it, and KiCad then loads it:

```text
$ kicad-part-importer --check-3d --verify-3d
Footprints checked: 1; model references: bare 1
  bare      lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod: DEMOTVS5.stp  -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp
3D check: 0 loaded, 1 with a model that did not load (1 of them with no 3D body, 0 with a dead extra reference next to one that loads), 0 without a model (KiCad 10.0.7)

$ kicad-part-importer --check-3d --fix-3d --verify-3d --yes
Footprints checked: 1; model references: bare 1
  bare      lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod: DEMOTVS5.stp  -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp
Changed 1 footprint file(s): 1 path(s) rewritten, 0 dead duplicate reference(s) removed
3D check: 1 loaded, 0 with a model that did not load, 0 without a model (KiCad 10.0.7)
```

Checking an import before writing it, then importing it:

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --verify-3d --dry-run
Plan: ul_DEMOBUCK1.zip -> power_management (lib_power_management)
  ...
Dry run: nothing written.
3D check: 3 loaded, 0 with a model that did not load, 0 without a model (KiCad 10.0.7)

$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --verify-3d --yes
...
✓ Added 3D model PKG0006A.stp
3D check: 3 loaded, 0 with a model that did not load, 0 without a model (KiCad 10.0.7)
```

In the JSON report, `verify_3d.failed` has one row per model that did not
load, with `reason` (KiCad's message) and `body_loaded`. `body_loaded` is
true when another `(model ...)` of the same footprint did load, so the part
still has its body and the failing block is a dead extra reference.
`verify_3d.no_body` lists the footprints that got no body at all.

A footprint KiCad cannot load at all (a malformed or newer-format file) has
no model to check, but it is a failure all the same: it is named, counted in
the summary, listed in `verify_3d.load_errors`, and the exit code is 1, with
`--check-3d` as with an import. Here the model paths are fine, one footprint
is not:

```text
$ kicad-part-importer --check-3d --verify-3d
Footprints checked: 2; model references: ok 2
✗ KiCad could not load SOD_BROKEN.kicad_mod: FootprintLoad returned None
3D check: 1 loaded, 0 with a model that did not load, 0 without a model, 1 that KiCad could not load (KiCad 10.0.7)
```

Open the footprint in KiCad's Footprint Editor to see why, and save it again
or replace it.

### Requirements and how KiCad is found

`--verify-3d` needs `kicad-cli` and a Python that can import `pcbnew`. That
is either KiCad's own Python in the same `bin` folder (the Windows install
has both) or the Python running the tool. It searches:

1. `--kicad-bin DIR`, else `KICAD_BIN`. When either is set, only that folder
   is used, and a folder without `kicad-cli` is an error. Setting
   `KICAD_BIN=/nonexistent` therefore hides every installed KiCad, which is
   how the test suite proves it runs without one.
2. Otherwise, the default KiCad 10 and 9 install folders on Windows
   (`%ProgramFiles%\KiCad\10.0\bin`, then `9.0`), then `kicad-cli` on `PATH`.

On Linux, install KiCad from your distribution or the KiCad PPA. `kicad-cli`
is then on `PATH`, and the system Python imports `pcbnew`. If you install
the tool in a virtual environment, create it with `--system-site-packages`
so that environment can import `pcbnew` too. On macOS, run the tool with
KiCad's bundled Python, or point `--kicad-bin` at a folder holding both
`kicad-cli` and a `python` that imports `pcbnew`.

KiCad 10 is tested (10.0.7). KiCad 9 is found but not tested. kicad-cli exits
0 even when models are missing, so the result is read from its messages. A
future KiCad that rewords them could hide failures; the test suite would
catch that.

## In CI

`--check-3d` is designed to gate a pull request: it needs no KiCad and exits
1 on any problem. Add `--verify-3d` where KiCad is installed. A full GitHub
Actions example for a private library repository is in
[private-library.md](private-library.md#a-ci-check-for-the-library).
