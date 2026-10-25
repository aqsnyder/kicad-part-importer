# Getting started

This page goes from nothing to a KiCad project that uses a categorized part
library. It covers installing the tool, creating the library, importing parts
and adding the library to the project. Every block of output below is from a
real run (see [How the examples were made](index.md#how-the-examples-were-made)).

- [1. Install](#1-install)
- [2. Create a library](#2-create-a-library)
- [3. Import a part](#3-import-a-part)
- [4. Check the library](#4-check-the-library)
- [5. Add the library to a KiCad project](#5-add-the-library-to-a-kicad-project)
- [6. Working from anywhere](#6-working-from-anywhere)
- [Next steps](#next-steps)

## 1. Install

You need Python 3.9 or newer. KiCad itself is only needed for `--verify-3d`,
which loads footprints in KiCad to prove their models load.

```bash
# Latest from GitHub
pip install git+https://github.com/aqsnyder/kicad-part-importer

# A fixed release (recommended for teams; see private-library.md)
pip install "git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0"

# From a checkout
git clone https://github.com/aqsnyder/kicad-part-importer
pip install ./kicad-part-importer
```

`pipx install git+https://github.com/aqsnyder/kicad-part-importer` works as
well and keeps the tool in its own environment. On Python 3.9 and 3.10 the
install pulls in `tomli` to read TOML config files. Nothing else is
installed.

You can also run the tool without installing it. The four modules
(`kicad_part_importer.py`, `kicad_lib_3d.py`, `kicad_lib_config.py` and
`kicad_lib_verify.py`) must stay together in one folder:

```bash
python path/to/kicad_part_importer.py --version
```

Check the install:

```text
$ kicad-part-importer --version
kicad-part-importer 0.1.0
```

## 2. Create a library

A library is a folder, usually its own git repository, often mounted into
each KiCad project as a git submodule. Here it lives inside an existing
project, `~/kicad/my_board`:

```text
$ cd ~/kicad/my_board && mkdir my_kicad_library && cd my_kicad_library
$ kicad-part-importer --init
Library root: /tmp/demo/kicad/my_board/my_kicad_library
✓ Wrote kicad-part-importer.toml: prefix 'lib_', 13 categories, mount ${KIPRJMOD}/my_kicad_library
Initializing library files...
  ✓ Created symbol library: lib_connectors.kicad_sym
  ✓ Created symbol library: lib_passives.kicad_sym
  ...
  ✓ Created footprint directory: lib_mechanicals_misc.pretty
✓ Library initialization complete

Next:
  kicad-part-importer --show-config
  kicad-part-importer part.zip --category connectors --link-3d --dry-run
  kicad-part-importer --add-to-project --project-dir <folder with sym-lib-table>

$ ls
3d_models
kicad-part-importer.toml
lib_fp
lib_sym
```

`--init` did two things:

1. It wrote `kicad-part-importer.toml`, which describes the library: the
   name prefix of the category libraries, the folder names, how projects
   reach the library (the *mount*, here `${KIPRJMOD}/my_kicad_library`), git
   behaviour and the list of categories. Commit this file with the library.
   From now on every command run inside the library reads it.
2. It created one symbol library (`lib_sym/<prefix><category>.kicad_sym`) and
   one footprint library (`lib_fp/<prefix><category>.pretty/`) per category,
   plus the shared model folder `3d_models/`.

```
my_board/                          <- KiCad project (the default project_dir)
├── my_board.kicad_pro
├── sym-lib-table
├── fp-lib-table
└── my_kicad_library/              <- library root, mounted as ${KIPRJMOD}/my_kicad_library
    ├── kicad-part-importer.toml   <- the library's own settings
    ├── lib_sym/
    │   ├── lib_connectors.kicad_sym
    │   └── ...                    (one symbol library per category)
    ├── lib_fp/
    │   ├── lib_connectors.pretty/
    │   └── ...                    (one footprint library per category)
    └── 3d_models/                 (every model, shared by all categories)
```

To use your own names, pass them to `--init`. Every setting is described in
[configuration.md](configuration.md). For example:

```bash
kicad-part-importer --init --library-prefix acme_ --model-dir models
```

Running `--init` in a folder that already holds `acme_*` libraries keeps
them and lists them as the categories. That is how you
[migrate an existing library](private-library.md#migrating-an-existing-library).
Edit the file afterwards to add descriptions or reorder the menu.

Put the library under version control now, so you can review each import as
a diff:

```text
$ git init -q -b main && git add -A && git commit -q -m "New part library" && git log --format=%s
New part library
```

`--show-config` prints what the tool will use and where it came from:

```text
$ kicad-part-importer --show-config
{
 "config_file": "/tmp/demo/kicad/my_board/my_kicad_library/kicad-part-importer.toml",
 "library_root": "/tmp/demo/kicad/my_board/my_kicad_library",
 "library_root_source": "discovered",
 "library_prefix": "lib_",
 "symbol_dir": "lib_sym",
 "footprint_dir": "lib_fp",
 "model_dir": "3d_models",
 "model_search_dirs": [],
 "project_dir": "/tmp/demo/kicad/my_board",
 "library_mount": "${KIPRJMOD}/my_kicad_library",
 "model_prefix": "${KIPRJMOD}/my_kicad_library/3d_models",
 "categories": [
  {
   "key": "connectors",
   "name": "lib_connectors",
   "description": "Connectors, headers, sockets, and interconnects"
  },
  ...
 ],
 "stock_symbol_libraries": [ ... ],
 "git_commit": false,
 "git_push": false,
 "git_message_prefix": ""
}
```

## 3. Import a part

Download a part in KiCad format from the vendor or a CAD-model site. This is a
SamacSys-style zip: a symbol, a KiCad 5 footprint, a STEP model, and files
for other CAD tools.

```text
$ python3 -m zipfile -l ~/Downloads/LIB_DEMOTVS5.zip
File Name                                             Modified             Size
DEMOTVS5/KiCad/DEMOTVS5.kicad_sym              2026-10-25 12:19:28          649
DEMOTVS5/KiCad/SOD_DEMO.kicad_mod              2026-10-25 12:19:28          595
DEMOTVS5/KiCad/DEMOTVS5.lib                    2026-10-25 12:19:28           29
DEMOTVS5/3D/DEMOTVS5.stp                       2026-10-25 12:19:28           62
DEMOTVS5/Altium/DEMOTVS5.SchLib                2026-10-25 12:19:28            1
license.txt                                    2026-10-25 12:19:28            6
```

Look first with `--dry-run`. It plans every write and writes nothing:

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --dry-run
Plan: LIB_DEMOTVS5.zip -> protection (lib_protection)
  symbol     DEMOTVS5               append    lib_sym/lib_protection.kicad_sym
  footprint  SOD_DEMO               add       lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod
             model: rewrite DEMOTVS5.stp -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOTVS5.stp (named by footprint)
  3D model   DEMOTVS5.stp           add       3d_models/DEMOTVS5.stp
  ignored    DEMOTVS5/Altium/DEMOTVS5.SchLib, DEMOTVS5/KiCad/DEMOTVS5.lib, license.txt
⚠ symbol DEMOTVS5: Footprint field 'SOD_DEMO' has no library prefix (KiCad needs lib_protection:SOD_DEMO)
Dry run: nothing written.
```

How to read the plan:

- `--category protection` picks the category. A library name
  (`lib_protection`) or the menu number (`12`) also works. Without
  `--category` (and without `--yes` / `--dry-run` / `--json`) the tool shows
  the category menu.
- `--link-3d` rewrites the footprint's model path. SamacSys names the model
  by its bare file name (`DEMOTVS5.stp`), which KiCad looks for next to the
  project file and does not find. The new path goes through the library
  mount, so it resolves in every project that mounts the library. See
  [3d-models.md](3d-models.md).
- Files that are not symbols, footprints or 3D models are listed as
  `ignored` and left alone.
- The warning concerns the symbol's Footprint field. It names the footprint
  without a library, and KiCad needs `lib_protection:SOD_DEMO`. The tool does
  not edit symbol fields, so set it in KiCad's Symbol Editor (or place the
  part and pick the footprint in the schematic).

Now import it. `--yes` means "no prompts" (it requires `--category`).
`--commit` commits exactly the files the import wrote:

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --yes --commit
Plan: LIB_DEMOTVS5.zip -> protection (lib_protection)
  ...
✓ Added symbol(s) from DEMOTVS5.kicad_sym to protection
✓ Added footprint SOD_DEMO.kicad_mod to protection
✓ Added 3D model DEMOTVS5.stp
[main 4f2bc66] Add components from LIB_DEMOTVS5.zip
 3 files changed, 41 insertions(+)
 create mode 100644 3d_models/DEMOTVS5.stp
 create mode 100644 lib_fp/lib_protection.pretty/SOD_DEMO.kicad_mod
✓ Committed 3 file(s): Add components from LIB_DEMOTVS5.zip
```

A TI / Ultra Librarian download carries several density variants of one land
pattern and no model reference at all, so `--link-3d` inserts one into each:

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --yes --commit
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
✓ Added symbol(s) from 2026-01-01_12-00-00.kicad_sym to power_management
...
✓ Committed 5 file(s): Add components from ul_DEMOBUCK1.zip

$ git log --format=%s
Add components from ul_DEMOBUCK1.zip
Add components from LIB_DEMOTVS5.zip
New part library
```

The planned import never clobbers anything. Importing the same zip again is
refused, and nothing is written (exit code 3):

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power_management --link-3d --yes
Plan: ul_DEMOBUCK1.zip -> power_management (lib_power_management)
  symbol     DEMOBUCK1              refused   lib_sym/lib_power_management.kicad_sym
  footprint  PKG0006A-IPC_A         identical lib_fp/lib_power_management.pretty/PKG0006A-IPC_A.kicad_mod
  ...
  3D model   PKG0006A.stp           identical 3d_models/PKG0006A.stp
...
✗ symbol DEMOBUCK1 already exists in lib_power_management (remove or rename it first)
Nothing written.
```

A footprint or model that exists with *other* content is refused the same
way. `--overwrite` replaces those. A symbol that already exists is always
refused.

### The interactive import

With none of the planned-run options, the tool asks for the category and
whether to delete the zip. Your answers are shown after the prompts:

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP.zip
Processing zip file: /tmp/demo/Downloads/LIB_DEMOCAP.zip

Found files:
  - Symbols: 1
  - Footprints: 1
  - 3D Models: 1

============================================================
KiCad Part Importer - Library Selection
============================================================
Select a library to add the component to:

 1. Connectors: Connectors, headers, sockets, and interconnects
 2. Passives: Resistors, capacitors, inductors, and other passive components
 ...
13. Mechanicals Misc: Mechanical parts, hardware, and miscellaneous components

 0. Skip (don't add to any library)
============================================================

Enter your choice (0-13): 2

Selected library: passives
✓ Added symbol(s) from DEMOCAP.kicad_sym to passives
✓ Added footprint CAP_DEMO.kicad_mod to passives
✓ Added 3D model DEMOCAP.stp

✓ Successfully processed 3/3 files

============================================================
Cleanup
============================================================
Zip file: LIB_DEMOCAP.zip
Location: /tmp/demo/Downloads/LIB_DEMOCAP.zip

Delete the zip file? (y/n): n
✓ Kept LIB_DEMOCAP.zip
```

The interactive path copies files as they are. It does not link models, it
overwrites a footprint or model of the same name, and it appends a symbol
even when one of that name exists. Prefer `--category ... --link-3d`. You
can still answer the menu by leaving out `--yes`:
`kicad-part-importer part.zip --link-3d` runs the planned import and shows
the menu.

## 4. Check the library

`--check-3d` checks every footprint's model path in the category libraries.
The part imported interactively above still names its model by a bare file
name:

```text
$ kicad-part-importer --check-3d
Footprints checked: 5; model references: bare 1, ok 4
  bare      lib_fp/lib_passives.pretty/CAP_DEMO.kicad_mod: DEMOCAP.stp  -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOCAP.stp
```

It exits 1 while problems remain. `--fix-3d` applies the fix shown after the
arrow:

```text
$ kicad-part-importer --check-3d --fix-3d --yes
Footprints checked: 5; model references: bare 1, ok 4
  bare      lib_fp/lib_passives.pretty/CAP_DEMO.kicad_mod: DEMOCAP.stp  -> ${KIPRJMOD}/my_kicad_library/3d_models/DEMOCAP.stp
Changed 1 footprint file(s): 1 path(s) rewritten, 0 dead duplicate reference(s) removed
```

With KiCad installed, add `--verify-3d` to load the footprints in KiCad and
prove the models really load. See [3d-models.md](3d-models.md).

## 5. Add the library to a KiCad project

`--add-to-project` adds category libraries to the project's
`sym-lib-table` and `fp-lib-table`. Both files must exist. KiCad writes them
once the project has a library on the *Project Specific Libraries* tab of
*Preferences > Manage Symbol Libraries* / *Manage Footprint Libraries*, or you
can create them by hand ([kicad-integration.md](kicad-integration.md#project-library-tables)
shows the content). The project folder defaults to the folder that holds the
library; `--project-dir` names another one. Your answer is shown after the
prompt:

```text
$ kicad-part-importer --add-to-project
Updating project library settings...

============================================================
Project Library Integration
============================================================
Select libraries to add to project settings:

 1. Connectors: Connectors, headers, sockets, and interconnects
 ...
 0. Add all libraries
============================================================

Enter your choice (0-13, comma-separated for multiple): 5,12

Selected libraries: power_management, protection
    + Adding symbol library: lib_power_management
    + Adding symbol library: lib_protection
  ✓ Added 2 symbol libraries to project
    + Adding footprint library: lib_power_management
    + Adding footprint library: lib_protection
  ✓ Added 2 footprint libraries to project
✓ Updated project library settings

$ cat ../sym-lib-table
(sym_lib_table
  (version 7)
  (lib (name "lib_power_management")(type "KiCad")(uri "${KIPRJMOD}/my_kicad_library/lib_sym/lib_power_management.kicad_sym")(options "")(descr "Power management ICs, regulators, and converters"))
  (lib (name "lib_protection")(type "KiCad")(uri "${KIPRJMOD}/my_kicad_library/lib_sym/lib_protection.kicad_sym")(options "")(descr "Protection devices, fuses, and ESD protection"))
)
```

Libraries already in a table are skipped, so running it again is safe. Open
the project in KiCad: the categories appear in the symbol chooser and in the
Footprint Editor, and the 3D viewer shows each part's body. More on tables,
mounts and submodules: [kicad-integration.md](kicad-integration.md).

## 6. Working from anywhere

The tool finds the library the way git finds `.git`. It walks up from the
current directory to the nearest folder holding a `kicad-part-importer.toml`
(or `.json`):

```text
$ cd lib_fp/lib_protection.pretty && kicad-part-importer --show-config | grep -E "library_root|config_file"
 "config_file": "/tmp/demo/kicad/my_board/my_kicad_library/kicad-part-importer.toml",
 "library_root": "/tmp/demo/kicad/my_board/my_kicad_library",
 "library_root_source": "discovered",
```

From outside the library (here the project folder, which holds no config
file) the tool falls back to the current directory. It then refuses to work
on a folder that is not a library:

```text
$ cd ~/kicad/my_board && kicad-part-importer --check-3d
✗ /tmp/demo/kicad/my_board is not a part library: it has no lib_sym/ or lib_fp/ folder (library root from: current directory). Run the command inside your library, pass --library DIR, or create one there with --init.
```

Name the library with `--library DIR`, or set
`KICAD_PART_IMPORTER_LIBRARY_ROOT` once in your shell profile:

```bash
kicad-part-importer --library my_kicad_library --check-3d
export KICAD_PART_IMPORTER_LIBRARY_ROOT=~/kicad/my_board/my_kicad_library
```

## Next steps

- [Command-line reference](cli.md): every option.
- [Configuration](configuration.md): the config file and every setting.
- [Vendor formats](vendor-formats.md): what each kind of download contains.
- [3D models](3d-models.md): linking, checking, fixing and verifying in KiCad.
- [Private company library](private-library.md): a team workflow with a
  private library repository and a CI check.
