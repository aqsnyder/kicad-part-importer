# KiCad integration

KiCad finds a library through the project's library tables, and a footprint's
3D model through the path in its `(model ...)` line. Both have to work in
every project, on every machine. This page explains how the tool writes both
and how to choose the *mount*, the path through which projects reach the
library.

- [Project library tables](#project-library-tables)
- [Mounts](#mounts)
- [A library inside each project (submodule)](#a-library-inside-each-project-submodule)
- [Projects next to the library](#projects-next-to-the-library)
- [A shared library through a path variable](#a-shared-library-through-a-path-variable)
- [Symbols and their Footprint field](#symbols-and-their-footprint-field)

## Project library tables

A KiCad project lists its own libraries in two files next to the
`.kicad_pro`:

- `sym-lib-table`: symbol libraries (`.kicad_sym` files);
- `fp-lib-table`: footprint libraries (`.pretty` folders).

`--add-to-project` adds the category libraries you pick to both. It writes
each entry through the library mount and fills the description from the
category. Entries whose name is already listed are left alone, so running it
again is harmless. The tables must exist. A project gets them when you add a
library on the *Project Specific Libraries* tab of *Preferences > Manage
Symbol Libraries* (and *Manage Footprint Libraries*), or you can create them
by hand:

```text
(sym_lib_table
  (version 7)
)
```

```text
(fp_lib_table
  (version 7)
)
```

The tool looks for them in the project folder (`project_dir`), which by
default is the folder that holds the library root. Point `--project-dir` (or
`project_dir` in the config file) elsewhere for a different layout. A run,
with the answer shown after the prompt:

```text
$ kicad-part-importer --add-to-project
...
Enter your choice (0-13, comma-separated for multiple): 5,12

Selected libraries: power_management, protection
    + Adding symbol library: lib_power_management
    + Adding symbol library: lib_protection
  ✓ Added 2 symbol libraries to project
    + Adding footprint library: lib_power_management
    + Adding footprint library: lib_protection
  ✓ Added 2 footprint libraries to project
✓ Updated project library settings

$ cat ../fp-lib-table
(fp_lib_table
  (version 7)
  (lib (name "lib_power_management")(type "KiCad")(uri "${KIPRJMOD}/my_kicad_library/lib_fp/lib_power_management.pretty")(options "")(descr "Power management ICs, regulators, and converters"))
  (lib (name "lib_protection")(type "KiCad")(uri "${KIPRJMOD}/my_kicad_library/lib_fp/lib_protection.pretty")(options "")(descr "Protection devices, fuses, and ESD protection"))
)
```

The edit is a text edit that expects KiCad's own formatting (one `(lib ...)`
per line), and keeps the file's line endings. KiCad reloads the tables when
the project is next opened.

For KiCad's *global* tables (all projects on a machine), add the libraries
in KiCad's library manager instead, using the same `${VAR}/...` paths as
below.

## Mounts

The mount (`library_mount`) is how a project reaches the library root,
written as a KiCad path variable plus an optional path. The tool writes
every model path and every table entry through it:

```text
<library_mount>/<model_dir>/<file>                    model path, e.g. ${KIPRJMOD}/my_kicad_library/3d_models/PKG0006A.stp
<library_mount>/<symbol_dir>/<library>.kicad_sym      sym-lib-table entry
<library_mount>/<footprint_dir>/<library>.pretty      fp-lib-table entry
```

| Layout | Mount | Good for |
|---|---|---|
| Library inside each project, usually a git submodule | `${KIPRJMOD}/<folder>` (the default) | Each project pins its own library version; everything resolves from the project folder, on any machine and in CI |
| Projects in a folder next to the library | `${KIPRJMOD}/../../<library>` | One working copy of the library for several projects in one repository |
| One shared checkout per machine | `${MY_LIB}` | Many projects, one library, no submodules. Every machine must define the variable |

`${KIPRJMOD}` is KiCad's name for the project folder. KiCad defines it while
a project is open, so a footprint opened in the Footprint Editor *without* a
project shows no 3D body. That is expected and does not mean the path is
wrong.

Pin the mount in the config file. `--init` writes the mount in effect, so a
library checked out under another folder name keeps writing the same paths.

## A library inside each project (submodule)

The default, and the most robust:

```bash
cd ~/kicad/my_board
git submodule add https://example.com/acme/acme_kicad_library.git acme_kicad_library
cd acme_kicad_library
kicad-part-importer --show-config | grep library_mount     # "${KIPRJMOD}/acme_kicad_library"
kicad-part-importer --add-to-project
```

Every project must check the submodule out under the folder name the mount
uses (`acme_kicad_library` above), because the model paths inside the
footprints say so. If a project needs another folder name, it cannot share
the footprints unchanged; keep one name everywhere.

## Projects next to the library

When the library sits beside a `boards/` folder, point `project_dir` at one
project. The default mount follows:

```text
$ cd ~/work/parts
$ kicad-part-importer --init --project-dir ../boards/board1 | head -n 2
Library root: /tmp/demo/work/parts
✓ Wrote kicad-part-importer.toml: prefix 'lib_', 13 categories, mount ${KIPRJMOD}/../../parts

$ grep -E "^(library_mount|project_dir)" kicad-part-importer.toml
library_mount = "${KIPRJMOD}/../../parts"
project_dir = "../boards/board1"

$ kicad-part-importer --show-config | grep -E "\"(project_dir|library_mount|model_prefix)\""
 "project_dir": "/tmp/demo/work/boards/board1",
 "library_mount": "${KIPRJMOD}/../../parts",
 "model_prefix": "${KIPRJMOD}/../../parts/3d_models",
```

Every project must then sit at the same depth (`boards/<name>/`), so that
`${KIPRJMOD}/../../parts` reaches the library from each of them. Use
`--add-to-project --project-dir ../boards/<name>` for each project.

## A shared library through a path variable

Define a path variable in KiCad (*Preferences > Configure Paths*, or an
environment variable of the same name) that points at the library checkout,
and use it as the mount:

```text
$ cd ~/libs/acme_kicad_library
$ kicad-part-importer --init --library-prefix acme_ --library-mount '${ACME_KICAD_LIB}' --config-format toml | head -n 3
Library root: /tmp/demo/libs/acme_kicad_library
✓ Wrote kicad-part-importer.toml: prefix 'acme_', 13 categories, mount ${ACME_KICAD_LIB}
Initializing library files...

$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --yes | head -n 4
Plan: LIB_DEMOTVS5.zip -> protection (acme_protection)
  symbol     DEMOTVS5               append    lib_sym/acme_protection.kicad_sym
  footprint  SOD_DEMO               add       lib_fp/acme_protection.pretty/SOD_DEMO.kicad_mod
             model: rewrite DEMOTVS5.stp -> ${ACME_KICAD_LIB}/3d_models/DEMOTVS5.stp (named by footprint)
```

Project tables get the variable too:

```text
$ cd ~/boards/sensor_board
$ kicad-part-importer --library ~/libs/acme_kicad_library --project-dir . --add-to-project
...
Enter your choice (0-13, comma-separated for multiple): 12
...
✓ Updated project library settings

$ cat sym-lib-table fp-lib-table
(sym_lib_table
  (version 7)
  (lib (name "acme_protection")(type "KiCad")(uri "${ACME_KICAD_LIB}/lib_sym/acme_protection.kicad_sym")(options "")(descr "Protection devices, fuses, and ESD protection"))
)
(fp_lib_table
  (version 7)
  (lib (name "acme_protection")(type "KiCad")(uri "${ACME_KICAD_LIB}/lib_fp/acme_protection.pretty")(options "")(descr "Protection devices, fuses, and ESD protection"))
)
```

Quote `${...}` on the command line so the shell does not expand it. For
`--verify-3d`, the tool sets the variable itself in the environment of its
own KiCad run, pointing at a scratch copy of the models it checks. You do not
need to define it to run the check.

## Symbols and their Footprint field

A symbol's *Footprint* field tells KiCad which footprint to use, as
`<footprint library>:<footprint>`. Vendors fill it in their own way, often
without a library or with a library named after the part. The importer
leaves the field as the vendor wrote it and warns when it does not name the
category library:

```text
⚠ symbol DEMOTVS5: Footprint field 'SOD_DEMO' has no library prefix (KiCad needs lib_protection:SOD_DEMO)
⚠ symbol DEMOLDO-33: Footprint field 'DEMOLDO-33:IC_DEMOLDO-33' names library 'DEMOLDO-33', not lib_power_management
```

Set it once in the Symbol Editor (*Symbol Properties > Footprint*). Every
later placement then picks the right footprint automatically.

`--migrate-schematic` handles the other direction. For a schematic whose
parts come from old project libraries, it copies the parts it can find into
the categories and rewrites the schematic's `lib_id` and Footprint
references to the category libraries, after saving a `.kicad_sch.bak`.
