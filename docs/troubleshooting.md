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
`case` and `--fix-3d` rewrites them to the real spelling.

## Platform notes

- **Windows consoles.** The check marks (`✓ ✗ ⚠`) print as `?` on a console
  that cannot show them (code page 1252). The tool replaces them rather than
  crashing. Set `PYTHONIOENCODING=utf-8`, or use Windows Terminal, to see
  them.
- **Line endings.** Footprints and symbol libraries keep their line endings
  (vendor files are often CRLF). Library tables keep theirs too. Config files
  written by `--init` use LF.
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
with `--json` never prompts, prints one JSON object on stdout, and uses the
exit codes above ([cli.md](cli.md#the-json-report)).

**Where do I report a problem?** In the
[issue tracker](https://github.com/aqsnyder/kicad-part-importer/issues).
Include `kicad-part-importer --version`, `--show-config` (remove anything
private) and the failing command with `--json` output if possible.
