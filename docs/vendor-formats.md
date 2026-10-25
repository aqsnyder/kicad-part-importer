# Vendor formats

Part downloads arrive as zips with a different layout from each source. The
importer does not depend on any of these layouts. It looks at every file in
the zip, at any depth, and sorts it by extension. This page shows what the
common sources ship and what the importer takes from each.

- [What the importer takes](#what-the-importer-takes)
- [TI / Ultra Librarian](#ti--ultra-librarian)
- [SamacSys / Component Search Engine](#samacsys--component-search-engine)
- [SnapEDA](#snapeda)
- [Other sources](#other-sources)
- [How a footprint gets its model](#how-a-footprint-gets-its-model)
- [Warnings in the plan](#warnings-in-the-plan)

The listings below are of small synthetic zips with the same layout as real
downloads (made-up part names, the same structure the test suite generates).
Download the KiCad format from each site; the importer cannot use files made
for other CAD tools.

## What the importer takes

| In the zip | Goes to | Notes |
|---|---|---|
| `*.kicad_sym` (KiCad 6+ symbol library) | appended to `<symbol_dir>/<category library>.kicad_sym` | Every top-level symbol in the file. A symbol whose name already exists in the target library is refused |
| `*.kicad_mod` (footprint, KiCad 5 `module` or KiCad 6+ `footprint` format) | `<footprint_dir>/<category library>.pretty/` | Kept byte for byte (line endings included) unless `--link-3d` changes its model path |
| `*.step`, `*.stp`, `*.stpz`, `*.wrl`, `*.wrz`, `*.igs`, `*.iges` | `<model_dir>/` (shared by all categories) | Reused when an identical file is already there |
| anything else (KiCad 5 `.lib`, Altium, Eagle, OrCAD files, readmes, licenses) | nothing | Listed as `ignored` in the plan and the JSON report |

The interactive import (a bare `kicad-part-importer part.zip`) is less strict
about models: it also copies `.stl`, `.3d` and any file with `3d` in its
name into the model folder. A planned run (`--category`, `--link-3d`,
`--yes`, `--dry-run`, `--json` ...) takes only the extensions in the table.

The zip itself is never changed. A planned run keeps it unless you pass
`--delete-zip`, which deletes it only after a clean import.

## TI / Ultra Librarian

A download from TI's product pages, or from Ultra Librarian with the KiCad
format selected, typically holds the STEP model at the top, a symbol library
named after a time stamp, and a `footprints.pretty` folder with one footprint
per density variant of the same land pattern (`-IPC_A`, `-IPC_B`, `-MFG`, or
`-L` / `-M` / `-N`):

```text
$ python3 -m zipfile -l ~/Downloads/ul_DEMOBUCK1.zip
File Name                                             Modified             Size
PKG0006A.stp                                   2026-10-25 12:16:58           62
KiCADv6/2026-01-01_12-00-00.kicad_sym          2026-10-25 12:16:58          658
KiCADv6/footprints.pretty/PKG0006A-IPC_A.kicad_mod 2026-10-25 12:16:58          570
KiCADv6/footprints.pretty/PKG0006A-IPC_B.kicad_mod 2026-10-25 12:16:58          570
KiCADv6/footprints.pretty/PKG0006A-MFG.kicad_mod 2026-10-25 12:16:58          570
```

What to expect:

- **No `(model ...)` in any footprint.** Imported as is, the part has no 3D
  body. `--link-3d` inserts a model block into each variant (zero offset and
  rotation, unit scale), pointing at the one model in the zip.
- **Every variant declares the first variant's name** inside the file. The
  plan warns about it. KiCad goes by the file name, so the variants still
  load as separate footprints.
- **The symbol's Footprint field has no library prefix**, so KiCad cannot
  resolve it until you set `<library>:<footprint>` in the Symbol Editor.
- Files use Windows line endings. The importer keeps them.

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --dry-run
Plan: ul_DEMOBUCK1.zip -> power_management (lib_power_management)
  symbol     DEMOBUCK1              append    lib_sym/lib_power_management.kicad_sym
  footprint  PKG0006A-IPC_A         add       lib_fp/lib_power_management.pretty/PKG0006A-IPC_A.kicad_mod
             model: insert ${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp (only model)
  footprint  PKG0006A-IPC_B         add       lib_fp/lib_power_management.pretty/PKG0006A-IPC_B.kicad_mod
             model: insert ${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp (only model)
  footprint  PKG0006A-MFG           add       lib_fp/lib_power_management.pretty/PKG0006A-MFG.kicad_mod
             model: insert ${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp (only model)
  3D model   PKG0006A.stp           add       3d_models/PKG0006A.stp
⚠ symbol DEMOBUCK1: Footprint field 'PKG0006A-IPC_A' has no library prefix (KiCad needs lib_power_management:PKG0006A-IPC_A)
⚠ footprint file PKG0006A-IPC_B.kicad_mod declares the name 'PKG0006A-IPC_A'
⚠ footprint file PKG0006A-MFG.kicad_mod declares the name 'PKG0006A-IPC_A'
Dry run: nothing written.
```

## SamacSys / Component Search Engine

Downloads from Component Search Engine (and from distributors that embed
SamacSys models) hold one folder per part. It contains a `KiCad/` folder with
the symbol and a KiCad 5 footprint, a `3D/` folder with the STEP model, and
folders for other CAD tools:

```text
$ python3 -m zipfile -l ~/Downloads/LIB_DEMOTVS5.zip
File Name                                             Modified             Size
DEMOTVS5/KiCad/DEMOTVS5.kicad_sym              2026-10-25 12:16:58          649
DEMOTVS5/KiCad/SOD_DEMO.kicad_mod              2026-10-25 12:16:58          595
DEMOTVS5/KiCad/DEMOTVS5.lib                    2026-10-25 12:16:58           29
DEMOTVS5/3D/DEMOTVS5.stp                       2026-10-25 12:16:58           62
DEMOTVS5/Altium/DEMOTVS5.SchLib                2026-10-25 12:16:58            1
license.txt                                    2026-10-25 12:16:58            6
```

What to expect:

- **The footprint names its model by a bare file name**
  (`(model DEMOTVS5.stp ...)`). KiCad resolves a bare name against the
  project folder, not the library, so the 3D viewer and the STEP export show
  the part without a body. `--link-3d` rewrites the path, keeping the
  offset, scale and rotation SamacSys set.
- The footprint is in the KiCad 5 `(module ...)` format. KiCad 6 and later
  read it and upgrade it when the footprint is next saved.
- The KiCad 5 symbol library (`.lib`) and the other tools' files are ignored.
  The `.kicad_sym` holds the same symbol.

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --dry-run --json
Plan: LIB_DEMOTVS5.zip -> protection (lib_protection)
  ...
{
 "command": "import",
 "zip": "/tmp/demo/Downloads/LIB_DEMOTVS5.zip",
 "library_root": "/tmp/demo/kicad/my_board/my_kicad_library",
 "dry_run": true,
 "link_3d": true,
 "written": [],
 "category": "protection",
 "symbols": [
  {
   "name": "DEMOTVS5",
   "source": "DEMOTVS5/KiCad/DEMOTVS5.kicad_sym",
   "target": "lib_sym/lib_protection.kicad_sym",
   "action": "append",
   "footprint_field": "SOD_DEMO"
  }
 ],
 "footprints": [
  {
   "name": "SOD_DEMO",
   "source": "DEMOTVS5/KiCad/SOD_DEMO.kicad_mod",
   "target": "lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod",
   "action": "add",
   "model": {
    "before": [
     "DEMOTVS5.stp"
    ],
    "after": [
     "${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp"
    ],
    "action": "rewrite",
    "rule": "named by footprint"
   }
  }
 ],
 "models": [
  {
   "name": "DEMOTVS5.stp",
   "source": "DEMOTVS5/3D/DEMOTVS5.stp",
   "target": "3d_models/DEMOTVS5.stp",
   "action": "add"
  }
 ],
 "ignored_files": [
  "DEMOTVS5/Altium/DEMOTVS5.SchLib",
  "DEMOTVS5/KiCad/DEMOTVS5.lib",
  "license.txt"
 ],
 "warnings": [
  "symbol DEMOTVS5: Footprint field 'SOD_DEMO' has no library prefix (KiCad needs lib_protection:SOD_DEMO)"
 ],
 "errors": [],
 "exit_code": 0,
 "ok": true
}
```

(With `--json` the plan lines go to stderr. They are shown here because the
terminal displays both streams.)

If you used the SamacSys Library Loader, you may already have a
`SamacSys_Parts.3dshapes` folder full of models. Copy it into the library and
list it in `model_search_dirs`. `--check-3d --fix-3d` will then point
existing footprints at those files
([private-library.md](private-library.md#migrating-an-existing-library)).

## SnapEDA

A SnapEDA KiCad download has the symbol and the footprint at the top level,
plus an import how-to and a license. The 3D model is often a separate
download, or missing:

```text
$ python3 -m zipfile -l ~/Downloads/DEMOLDO-33.zip
File Name                                             Modified             Size
DEMOLDO-33.kicad_sym                           2026-10-25 12:16:58          652
IC_DEMOLDO-33.kicad_mod                        2026-10-25 12:16:58          457
how-to-import.htm                              2026-10-25 12:16:58           40
License.txt                                    2026-10-25 12:16:58            6
```

What to expect:

- **The symbol's Footprint field names a library called after the part**
  (`DEMOLDO-33:IC_DEMOLDO-33`). The plan warns that it should name the
  category library instead.
- **No model, and no `(model ...)` in the footprint.** The plan warns
  `no 3D model`. Put the STEP file in the zip before importing (any folder
  works), or copy it into the model folder and add the model in KiCad's
  Footprint Editor.

```text
$ kicad-part-importer ~/Downloads/DEMOLDO-33.zip --category power_management --link-3d --dry-run
Plan: DEMOLDO-33.zip -> power_management (lib_power_management)
  symbol     DEMOLDO-33             append    lib_sym/lib_power_management.kicad_sym
  footprint  IC_DEMOLDO-33          add       lib_fp/lib_power_management.pretty/IC_DEMOLDO-33.kicad_mod
             model: none (no model offered)
  ignored    License.txt, how-to-import.htm
⚠ symbol DEMOLDO-33: Footprint field 'DEMOLDO-33:IC_DEMOLDO-33' names library 'DEMOLDO-33', not lib_power_management
⚠ footprint IC_DEMOLDO-33: no 3D model (no model offered)
Dry run: nothing written.
```

## Other sources

Any zip that holds `.kicad_sym`, `.kicad_mod` or model files works the same
way, for example a part you exported from another library or a
manufacturer's own KiCad download. If a source ships a bare `.kicad_mod` and a
`.step` outside a zip, zip them together first.

## How a footprint gets its model

With `--link-3d`, the importer chooses one model from the zip for each
footprint. The first rule that gives a single answer wins:

| Rule (as reported in `model.rule`) | Picks |
|---|---|
| `named by footprint` | The model the footprint already names, matched by file name (any path form, any letter case) |
| `only model` | The only model in the zip |
| `same stem` | The model whose name equals the footprint name without its density suffix (`-L`, `-M`, `-N`, `_L`, `_M`, `_N`, `-IPC_A`, `-IPC_B`, `-IPC_C`, `-MFG`) |
| `stem prefix` | The longest model name the footprint name starts with |
| `ambiguous: ...` / `no model offered` | Nothing; the footprint is left as it is and the plan says why |

Then it writes `<model_prefix>/<file>` (by default
`<library_mount>/<model_dir>/<file>`). If the footprint already has a
`(model ...)` naming that file, only the path is replaced, and offset, scale
and rotation are kept. If the footprint has none, a block with zero offset
and rotation and unit scale is inserted. A footprint that names a
*different* model than the one chosen is left alone, with a warning.

When no model from the zip is chosen, a footprint that names a model the
library already has (by file name, in the model folder or a
`model_search_dirs` folder) is pointed at the library's copy.

## Warnings in the plan

Warnings never stop an import. They point at things worth a look:

| Warning | Meaning |
|---|---|
| `Footprint field 'X' has no library prefix (KiCad needs LIB:X)` | Set the symbol's Footprint field to `LIB:X` in KiCad, or KiCad will not find the footprint |
| `Footprint field 'A:X' names library 'A', not LIB` | Same, for a field that names the vendor's library |
| `footprint file F declares the name 'N'` | The name inside the file differs from the file name. KiCad uses the file name |
| `symbol S also exists in LIB2` / `footprint F also exists in LIB2.pretty` | The same name is already in another category |
| `footprint F: no 3D model (...)` | Nothing to link, see the rule given |
| `footprint F names A, not B; left as is` | The footprint names a different model than the one chosen |
| `footprint F: model R is not in 3d_models/` | A footprint without a model in the zip names a file the library does not have |

Errors, by contrast, stop the import before anything is written (exit code
3): a symbol that exists, a footprint or model that exists with other content
(unless `--overwrite`), two footprints or two models of one name in the zip,
or a zip with nothing to import.
