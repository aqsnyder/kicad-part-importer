# Troubleshooting and FAQ

Every message below is copied from a real run. Exit codes: 0 ok, 1 failed,
2 usage, 3 refused (nothing written).

- [Library and settings](#library-and-settings)
- [Importing](#importing)
- [3D models and KiCad](#3d-models-and-kicad)
- [Platform notes](#platform-notes)
- [FAQ](#faq)

## Library and settings

### Not a part library

```text
$ kicad-part-importer --check-3d
✗ /tmp/demo is not a part library: it has no lib_sym/ or lib_fp/ folder (library root from: current directory). Run the command inside your library, pass --library DIR, or create one there with --init.
```

Exit code 2. The tool did not find a library. It walked up from the current
directory without finding a `kicad-part-importer.toml` / `.json`, fell back
to the current directory, and that folder has no symbol or footprint folder.
It stops instead of creating files in the wrong place. Fix it in one of
these ways:

- `cd` into the library (or any folder below it);
- pass `--library path/to/library`, or set `KICAD_PART_IMPORTER_LIBRARY_ROOT`;
- if this is the library but it has no config file yet, run
  `kicad-part-importer --init` in it (an existing library keeps its files);
- if your folder names differ from `lib_sym` / `lib_fp`, say so with
  `--symbol-dir` / `--footprint-dir`, or better, in the config file.

`kicad-part-importer --show-config` shows which root the tool picked and why
(`library_root_source`).

### Two config files

```text
$ kicad-part-importer --check-3d
✗ both kicad-part-importer.toml and kicad-part-importer.json are in /tmp/demo/acme/acme_kicad_library; keep one
```

Delete one of them. The tool will not guess which one you meant.

### Unknown setting, bad value

```text
$ kicad-part-importer --config /tmp/demo/bad.toml --show-config
✗ config file /tmp/demo/bad.toml: unknown setting(s) library_prefx (known: library_root, library_prefix, symbol_dir, footprint_dir, model_dir, model_search_dirs, project_dir, library_mount, model_prefix, categories, stock_symbol_libraries, git_commit, git_push, git_message_prefix)

$ kicad-part-importer --library-mount 'acme_kicad_library' --show-config
✗ library_mount 'acme_kicad_library' must start with a KiCad path variable, e.g. ${KIPRJMOD}/my_kicad_library

$ KICAD_PART_IMPORTER_GIT_PUSH=maybe kicad-part-importer --show-config
✗ KICAD_PART_IMPORTER_GIT_PUSH='maybe': use 1/true/yes/on or 0/false/no/off
```

Typos are errors on purpose: a misspelled setting would otherwise fall back
to its default without a word. The rules are in
[configuration.md](configuration.md#validation).

### `library_root` in a discovered file

A `kicad-part-importer.toml` found in (or above) the current directory cannot
move the library elsewhere, and saying `library_root = ...` in it is an
error. Put `library_root` only in a file you name with `--config` or
`KICAD_PART_IMPORTER_CONFIG`.

### TOML needs Python 3.11 or tomli

```text
$ kicad-part-importer --check-3d          # Python 3.9, tool run from a checkout, no tomli
✗ a .toml config needs Python 3.11+ or the tomli package (pip install tomli); a .json config works everywhere
```

Installed with pip, the tool brings `tomli` along on Python 3.9 and 3.10. You
see this message only when running the modules from a checkout on an old
Python. Install `tomli`, or use a `.json` config file. On such a Python,
`--init` writes `kicad-part-importer.json` by itself.

### `--init` refuses

```text
$ cd lib_sym && kicad-part-importer --init
✗ /tmp/demo/acme/acme_kicad_library/lib_sym is inside the library /tmp/demo/acme/acme_kicad_library (kicad-part-importer.toml there). Pass --library DIR to create a separate library here anyway.
```

You are inside an existing library, and a nested one is rarely what you
want. Pass `--library DIR` if it is.

`--init` also refuses settings flags when the library already has a config
file:

```text
$ kicad-part-importer --init --library-prefix acme_
✗ /tmp/demo2/my_kicad_library/kicad-part-importer.toml already exists and --init does not change it: edit the file, or run again without the settings flags (library_prefix)

$ kicad-part-importer --init | head -n 3
Library root: /tmp/demo2/my_kicad_library
- kicad-part-importer.toml already exists; kept it (edit it to change the settings)
Initializing library files...
```

Edit the file instead. Run `--init` without flags to create the folders and
libraries the file describes.

## Importing

### `--category is required without prompts`

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP.zip --yes
✗ --category is required without prompts (one of: c_74xx, connectors, ics, power)
```

`--yes`, `--dry-run` and `--json` never prompt, so the category must be on
the command line: its key, its library name, or its menu number.

### Unknown category

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP.zip --category capacitors --yes
✗ unknown category 'capacitors' (one of: c_74xx, connectors, ics, power)
```

The categories come from the library's config file. `--show-config` lists
them. Add one by adding a `[[categories]]` table, then run `--init` again to
create its empty libraries.

### `cannot read zip`

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP_PART.zip --category passives --yes
✗ cannot read zip: File is not a zip file
```

Exit code 2, before anything is written, with or without prompts. The file
is not a zip archive, or not a whole one: a download that was cut short, or
a web page saved under a `.zip` name. A zip with a damaged file in it says
`Bad CRC-32 for file '...'` instead. Download the part again.

### Refused, nothing written (exit code 3)

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power --yes
Plan: ul_DEMOBUCK1.zip -> power (acme_power)
  symbol     DEMOBUCK1              refused   lib_sym/acme_power.kicad_sym
  footprint  PKG0006A-IPC_A         refused   lib_fp/acme_power.pretty/PKG0006A-IPC_A.kicad_mod
  footprint  PKG0006A-IPC_B         refused   lib_fp/acme_power.pretty/PKG0006A-IPC_B.kicad_mod
  footprint  PKG0006A-MFG           refused   lib_fp/acme_power.pretty/PKG0006A-MFG.kicad_mod
  3D model   PKG0006A.stp           identical models/PKG0006A.stp
...
✗ symbol DEMOBUCK1 already exists in acme_power (remove or rename it first)
✗ lib_fp/acme_power.pretty/PKG0006A-IPC_A.kicad_mod exists with different content (use --overwrite to replace)
✗ lib_fp/acme_power.pretty/PKG0006A-IPC_B.kicad_mod exists with different content (use --overwrite to replace)
✗ lib_fp/acme_power.pretty/PKG0006A-MFG.kicad_mod exists with different content (use --overwrite to replace)
Nothing written.
```

The part is already in the library. The footprints differ here because the
first import used `--link-3d` and this one did not. Nothing was written.
If you mean to update the part:

- footprints and models: add `--overwrite`;
- the symbol: remove it from the symbol library in KiCad's Symbol Editor (or
  rename one of them), then import again. The tool never replaces a symbol,
  because a symbol library cannot hold two symbols of one name.

### Prompting commands with `--yes`

```text
$ kicad-part-importer --migrate --yes
✗ --migrate asks questions; run without --yes/--dry-run/--json
```

`--add-to-project`, `--migrate` and `--migrate-schematic` ask which category
or library to use, so they cannot run without prompts.

### No answer at the prompt (stdin closed)

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP.zip < /dev/null 2>&1 | tail -n 2
Enter your choice (0-13):
✗ No answer at the prompt (stdin closed); stopped. Pass --category (one of: connectors, passives, semiconductors_discretes, ics_general, power_management, mcus_soc, memory_storage, rf_communication, sensors, optoelectronics_displays, electromechanical, protection, mechanicals_misc) and --yes to import without prompts.
```

Exit code 2. The command asked a question and got no answer: it ran from a
script, CI or an agent with no terminal, or you pressed Ctrl+C. Nothing was
written after that point. For an import, give the category on the command
line. `--add-to-project` and the migration commands have no flag for their
answers; run them in a terminal. With no answer to "Delete the zip file?"
the import itself is done and the zip is kept.

### A non-UTF-8 file in a vendor zip

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOCAP_CP1252.zip --category passives --yes
Plan: LIB_DEMOCAP_CP1252.zip -> passives (lib_passives)
  footprint  CAP_DEMO               add       lib_fp/lib_passives.pretty/CAP_DEMO.kicad_mod
  3D model   DEMOCAP.stp            add       3d_models/DEMOCAP.stp
✗ DEMOCAP/KiCad/DEMOCAP.kicad_sym is not UTF-8 text (byte 0xb5 at position 267); KiCad files are UTF-8: save it as UTF-8 and try again
Nothing written.
```

Exit code 3. KiCad writes UTF-8; this file was saved in another encoding
(here Windows-1252, where `µ` is the byte `0xb5`). Unpack the zip, open the
file in an editor, save it as UTF-8, zip it again and import that.

The same error can name a symbol library of the library itself:

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --yes | tail -n 2
✗ lib_sym/lib_passives.kicad_sym is not UTF-8 text (byte 0xb5 at position 266); KiCad files are UTF-8: save it as UTF-8 and try again
Nothing written.
```

The plan reads the symbol names of every category (to refuse a duplicate,
and to warn about a name another category has), so such a file stops every
planned import, whatever its category. Save it as UTF-8 in an editor.

### `--fix-3d` alone

```text
$ kicad-part-importer --fix-3d
✗ --fix-3d and --all-footprint-libs need --check-3d
```

Use `--check-3d --fix-3d`.

### The symbol does not find its footprint in KiCad

The plan warned about it:

```text
⚠ symbol DEMOTVS5: Footprint field 'SOD_DEMO' has no library prefix (KiCad needs lib_protection:SOD_DEMO)
```

Set the symbol's Footprint field to the given value in the Symbol Editor.
The tool leaves symbol fields as the vendor wrote them.

## Projects, migration and git

### Project library tables not found

```text
$ kicad-part-importer --add-to-project
Updating project library settings...
✗ Project library tables not found: /tmp/demo/kicad/my_board needs both sym-lib-table and fp-lib-table (KiCad writes them; see docs/kicad-integration.md)
```

Exit code 1. The project folder (`project_dir`, by default the folder that
holds the library) has no `sym-lib-table` / `fp-lib-table` yet. Let KiCad
create them, or create them by hand
([kicad-integration.md](kicad-integration.md#project-library-tables)), or
point `--project-dir` at the right folder.

### `--commit does not apply to --add-to-project`

```text
$ kicad-part-importer --add-to-project --commit
⚠ --commit does not apply to --add-to-project: the tables are project files; commit them in the project
Updating project library settings...
...
✓ Updated project library settings
```

The tables belong to the project, often a different repository than the
library, so the tool leaves them for you to commit there. The same holds
for the schematic `--migrate-schematic` rewrites: `--commit` commits the
symbols and footprints it copied into the library, not the schematic.

### Not committed (git ignores them)

```text
$ kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --yes --commit | grep -i committed
⚠ Not committed (git ignores them): 3d_models/DEMOTVS5.stp
✓ Committed 2 file(s): Add components from LIB_DEMOTVS5.zip
```

Exit code 0. The repository ignores the model folder (here the project's
`.gitignore` lists `my_kicad_library/3d_models/`), and `git add` refuses an
ignored file, so the tool commits the symbol and the footprint and leaves
the model out. The model is written all the same. If the models belong in
the repository, remove the folder from `.gitignore` and commit them. With
`--json`, the report's `warnings` names the files too.

### A symbol is not migrated again

```text
$ kicad-part-importer --migrate old_parts.kicad_sym | tail -n 6

============================================================
Migration Complete
============================================================
✓ Migrated 0 symbol(s)
✗ 1 symbol(s) or footprint(s) not copied (see above)
```

Exit code 1. Above the summary the run says
`⚠ OLDREG already exists in lib_power_management; not copied again (remove
or rename one of them first)`. A symbol library cannot hold two symbols of
one name, so `--migrate` and `--migrate-schematic` never append a second
one. After `--migrate`, if the symbol in the category is the one you want,
there is nothing to do. `--migrate-schematic` also leaves that part's
references in the schematic as they were, so the schematic still uses the
old library: point those parts at the category's symbol in KiCad's
Schematic Editor (the *Change Symbols* dialog sets a symbol's library link),
or remove the symbol from the category and run the migration again.

## 3D models and KiCad

### KiCad not found

```text
$ kicad-part-importer --check-3d --verify-3d
✗ KiCad not found: pass --kicad-bin <KiCad bin folder> or set KICAD_BIN

$ KICAD_BIN=/nonexistent kicad-part-importer --check-3d --verify-3d
✗ no kicad-cli in KICAD_BIN /nonexistent
```

Exit code 2, before anything is written. `--verify-3d` needs `kicad-cli`
and a Python that imports `pcbnew`. On Windows the default KiCad 10 / 9
install is found by itself. On Linux, `kicad-cli` must be on `PATH` and the
tool must run with a Python that imports `pcbnew` (a virtual environment
created with `--system-site-packages`). When `KICAD_BIN` or `--kicad-bin` is
set, only that folder is used. A stale `KICAD_BIN` in your shell profile
therefore hides an installed KiCad; unset it. See
[3d-models.md](3d-models.md#requirements-and-how-kicad-is-found).

If the tool finds `kicad-cli` but no Python with `pcbnew`, it says so:

```text
$ kicad-part-importer --check-3d --verify-3d --kicad-bin /tmp/demo2/fake-kicad-bin
✗ kicad-cli found in /tmp/demo2/fake-kicad-bin, but no Python with pcbnew next to it, and this Python cannot import pcbnew: run the tool with KiCad's Python, or point --kicad-bin / KICAD_BIN at a folder holding both
```

### `File not found` from `--verify-3d`

```text
✗ 3D model did not load: SOD_DEMO.kicad_mod: File not found: DEMOTVS5.stp
```

The footprint names its model by a path KiCad cannot resolve from a project.
Here it is a bare file name. `kicad-part-importer --check-3d --fix-3d --yes`
rewrites it when the file is in the library. See
[3d-models.md](3d-models.md#proving-it-in-kicad---verify-3d).

### `KiCad could not load` from `--verify-3d`

```text
✗ KiCad could not load SOD_BROKEN.kicad_mod: FootprintLoad returned None
3D check: 1 loaded, 0 with a model that did not load, 0 without a model, 1 that KiCad could not load (KiCad 10.0.7)
```

Exit code 1, even when every model path is fine. KiCad's `pcbnew` could not
read the footprint file at all (a syntax error, an unknown token, a format
newer than your KiCad), so its model could not be checked either. Open it in
the Footprint Editor, fix or re-save it, and run the check again.

### `--check-3d` is clean but KiCad shows no body

- **Footprint Editor without a project.** `${KIPRJMOD}` is only defined while
  a project is open. Open the footprint from a project (or the board), or
  look at it in the 3D viewer of the board.
- **The project mounts the library under another folder name.** The mount in
  the model paths (`--show-config`, `library_mount`) must match how the
  project reaches the library, for example the submodule folder name. See
  [kicad-integration.md](kicad-integration.md#mounts).
- **A `${VAR}` mount that is not defined in KiCad.** Define it under
  *Preferences > Configure Paths* on every machine.
- **The file is not a readable model.** `--verify-3d` reports it as
  `not a readable model file`. Download the model again.

### Works on Windows, fails on Linux

Linux file names are case-sensitive. `--check-3d` reports such paths as
`case`, whether the file name or a folder in the path is spelled with other
letter case (`3D_Models/X.step` for `3d_models/X.step`), and `--fix-3d`
rewrites them to the real spelling.

## Platform notes

- **Windows consoles.** The check marks (`✓ ✗ ⚠`) print as `?` on a console
  that cannot show them (code page 1252). The tool replaces them rather than
  crashing. Set `PYTHONIOENCODING=utf-8`, or use Windows Terminal, to see
  them.
- **Line endings.** Footprints and symbol libraries keep their line endings
  (vendor files are often CRLF). Library tables and the schematics
  `--migrate-schematic` rewrites keep theirs too, and a footprint it copies
  keeps its bytes. New symbol libraries and config files written by `--init`
  use LF, as KiCad does, on every OS.
- **Long paths on Windows.** A library several folders deep inside a long
  path can exceed the classic 260-character limit when KiCad or Python
  opens it. Enable long paths in Windows, or keep libraries closer to the
  drive root.

## FAQ

**Does the tool download parts?** No. It works on zips you have already
downloaded, under each vendor's terms, and never contacts a server.

**Which KiCad versions?** Footprints in the KiCad 5 and later formats, and
symbol libraries in the KiCad 6+ `.kicad_sym` format (KiCad 5 `.lib` files
are ignored). `--verify-3d` is tested with KiCad 10.0.7 and also finds
KiCad 9. Without `--verify-3d`, KiCad does not need to be installed.

**Is the vendor zip changed?** Never. It is deleted only with
`--delete-zip` after a clean import, or when you answer `y` in the
interactive import.

**Do I need git?** No. Git is used only for `--commit`, `--push` and the
`git_commit` / `git_push` settings.

**Can I rename a category later?** Change its `key` or `description` in the
config file at any time. Changing its library *name* means renaming the
`.kicad_sym` file and the `.pretty` folder yourself, then updating project
tables and symbols' Footprint fields. The tool does not rename libraries.

**Can I use it from a script or an agent?** Yes: `--yes` or `--dry-run`
with `--json` never prompts, prints one JSON object on stdout (usage errors
included), and uses the exit codes above ([cli.md](cli.md#the-json-report)).
A command that does prompt stops with exit code 2 when stdin is closed,
instead of waiting or crashing.

**Where do I report a problem?** In the
[issue tracker](https://github.com/aqsnyder/kicad-part-importer/issues).
Include `kicad-part-importer --version`, `--show-config` (remove anything
private) and the failing command with `--json` output if possible.
