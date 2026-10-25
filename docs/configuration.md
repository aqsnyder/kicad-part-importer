# Configuration

Everything that could differ between one company's library and another's is
a setting. That covers the name prefix, the categories and their
descriptions, the folder names, how projects reach the library, extra folders
to search for 3D models, and what the tool does with git. Settings live in a
config file inside the library, so the library describes itself and the tool
needs no flags in daily use.

- [Which library](#which-library)
- [Where settings come from](#where-settings-come-from)
- [The config file](#the-config-file)
- [Settings reference](#settings-reference)
- [Categories](#categories)
- [Git settings](#git-settings)
- [Examples](#examples)
- [Validation](#validation)

## Which library

The *library root* is the folder that holds the symbol folder, the footprint
folder, the model folder and the config file. The tool uses, in this order:

1. `--library DIR` (also spelled `--library-root DIR`);
2. the environment variable `KICAD_PART_IMPORTER_LIBRARY_ROOT`;
3. `library_root` in a config file named with `--config FILE` or
   `KICAD_PART_IMPORTER_CONFIG`;
4. **discovery**: the nearest folder at or above the current directory that
   holds `kicad-part-importer.toml` or `kicad-part-importer.json`, the way git
   finds `.git` (skipped when a config file is named explicitly);
5. the current directory.

The tool never assumes it lives inside the library, and never looks at its
own install location. Run it anywhere inside a library and it works on that
library:

```text
$ cd lib_fp/lib_protection.pretty && kicad-part-importer --show-config | grep -E "library_root|config_file"
 "config_file": "/tmp/demo/kicad/my_board/my_kicad_library/kicad-part-importer.toml",
 "library_root": "/tmp/demo/kicad/my_board/my_kicad_library",
 "library_root_source": "discovered",
```

With no config file anywhere above, the current directory is used:

```text
$ mkdir -p /tmp/demo/notalib && cd /tmp/demo/notalib && kicad-part-importer --show-config | grep -E "\"(library_root|library_root_source|config_file)\""
 "config_file": null,
 "library_root": "/tmp/demo/notalib",
 "library_root_source": "current directory",
```

Commands that work on a library refuse a root that has neither the symbol
folder nor the footprint folder, so a typo or the wrong directory cannot
scatter files around (see
[troubleshooting](troubleshooting.md#not-a-part-library)).

## Where settings come from

Highest first:

1. command-line flags (`--library-prefix`, `--model-dir`, `--commit` ...);
2. environment variables `KICAD_PART_IMPORTER_<SETTING>`, the setting name in
   upper case (`KICAD_PART_IMPORTER_LIBRARY_PREFIX`);
3. the config file: the one named with `--config FILE` or
   `KICAD_PART_IMPORTER_CONFIG`, else `kicad-part-importer.toml` or
   `kicad-part-importer.json` in the library root (one of them, not both);
4. the defaults.

A setting you do not give keeps coming from the next source down, so a flag
overrides one setting for one run and leaves the rest of the file in effect:

```text
$ KICAD_PART_IMPORTER_GIT_COMMIT=0 kicad-part-importer --show-config | grep git_commit
 "git_commit": false,

$ kicad-part-importer --library-prefix xyz_ --show-config | grep -E "\"(library_prefix|library_root_source)\""
 "library_root_source": "discovered",
 "library_prefix": "xyz_",
```

`kicad-part-importer --show-config` prints every effective setting, the
config file it read (`config_file`) and how it found the library root
(`library_root_source`).

## The config file

- **Name and place:** `kicad-part-importer.toml` or `kicad-part-importer.json`
  in the library root. `--init` writes one for you (TOML by default,
  `--config-format json` for JSON) from the settings in effect, with a
  comment above every setting. Copy
  [examples/kicad-part-importer.toml](../examples/kicad-part-importer.toml) or
  [examples/kicad-part-importer.json](../examples/kicad-part-importer.json) to
  start from every default instead.
- **Format:** TOML needs Python 3.11+ or the `tomli` package, which the
  install pulls in on Python 3.9 and 3.10. JSON works everywhere. When the
  tool runs from a checkout on an old Python without `tomli`, `--init` writes
  JSON.
- **Paths** in the file (`project_dir`, `library_root`) are relative to the
  file's folder. Paths on the command line and in environment variables are
  relative to the current directory.
- **`library_root`** is allowed only in a file named with `--config` or
  `KICAD_PART_IMPORTER_CONFIG`. A file found in a library cannot move the
  library somewhere else.
- **Unknown keys** are an error, so a typo cannot silently fall back to a
  default.
- **Commit the file** with the library. Everyone who clones the library then
  gets the same names, mount and git behaviour.

## Settings reference

| Setting | Type | Default | Flag | Environment variable |
|---|---|---|---|---|
| `library_root` | path | see [Which library](#which-library) | `--library` | `KICAD_PART_IMPORTER_LIBRARY_ROOT` |
| `library_prefix` | string (may be empty) | `"lib_"` | `--library-prefix` | `KICAD_PART_IMPORTER_LIBRARY_PREFIX` |
| `symbol_dir` | folder in the library | `"lib_sym"` | `--symbol-dir` | `KICAD_PART_IMPORTER_SYMBOL_DIR` |
| `footprint_dir` | folder in the library | `"lib_fp"` | `--footprint-dir` | `KICAD_PART_IMPORTER_FOOTPRINT_DIR` |
| `model_dir` | folder in the library | `"3d_models"` | `--model-dir` | `KICAD_PART_IMPORTER_MODEL_DIR` |
| `model_search_dirs` | list of folders in the library | `[]` | `--model-search-dir` (repeat) | `KICAD_PART_IMPORTER_MODEL_SEARCH_DIRS` (joined with `:` on Linux / macOS, `;` on Windows) |
| `project_dir` | path | the folder that holds the library root | `--project-dir` | `KICAD_PART_IMPORTER_PROJECT_DIR` |
| `library_mount` | `${VAR}` or `${VAR}/path` | `${KIPRJMOD}/<path from project_dir to the library root>` | `--library-mount` | `KICAD_PART_IMPORTER_LIBRARY_MOUNT` |
| `model_prefix` | string | `<library_mount>/<model_dir>` | `--model-prefix` | `KICAD_PART_IMPORTER_MODEL_PREFIX` |
| `categories` | list of keys or tables | the 13 below | (file only) | (file only) |
| `stock_symbol_libraries` | list of strings | KiCad's common libraries (below) | (file only) | (file only) |
| `git_commit` | boolean | `false` | `--commit` / `--no-commit` | `KICAD_PART_IMPORTER_GIT_COMMIT` |
| `git_push` | boolean | `false` | `--push` / `--no-push` | `KICAD_PART_IMPORTER_GIT_PUSH` |
| `git_message_prefix` | string | `""` | (none) | `KICAD_PART_IMPORTER_GIT_MESSAGE_PREFIX` |

Two more variables are not settings: `KICAD_PART_IMPORTER_CONFIG` (the
config file to read, like `--config`) and `KICAD_BIN` (KiCad's `bin` folder,
like `--kicad-bin`). Boolean variables take `1`, `true`, `yes`, `on` or `0`,
`false`, `no`, `off`, in any case.

What each setting does, with an example value:

**`library_prefix`**: the category libraries are named
`<library_prefix><key>`. With `"acme_"` the category `power` lives in
`lib_sym/acme_power.kicad_sym` and `lib_fp/acme_power.pretty`. `--check-3d`
looks only at `<footprint_dir>/<library_prefix>*.pretty`, and
`--migrate-schematic` treats any library with the prefix as already
migrated. Library names cannot hold `/ \ : "`.

```toml
library_prefix = "acme_"
```

**`symbol_dir`, `footprint_dir`, `model_dir`**: the three folders, as paths
inside the library root (`..` and absolute paths are refused). All
categories share the one model folder.

```toml
symbol_dir = "symbols"
footprint_dir = "footprints"
model_dir = "packages3d"
```

**`model_search_dirs`**: more folders, inside the library root, where
`--check-3d --fix-3d` looks for a model a footprint names by another path,
after `model_dir`. Use it for an old export that you keep in the library.

```toml
model_search_dirs = ["vendor/SamacSys_Parts.3dshapes"]
```

**`project_dir`**: the KiCad project folder whose `sym-lib-table` and
`fp-lib-table` `--add-to-project` edits. It also anchors the default mount.

```toml
project_dir = "../.."   # library at <project>/libs/<library>
```

**`library_mount`**: how a project reaches the library root, written as a
KiCad path variable, optionally followed by a path. Model paths
(`--link-3d`, `--fix-3d`) and library-table entries (`--add-to-project`) are
written through it, and `--check-3d` recognizes library model paths by it.
Pin it in the config file so it does not depend on what a checkout folder is
called. See [kicad-integration.md](kicad-integration.md#mounts) for the
choices.

```toml
library_mount = "${KIPRJMOD}/acme_kicad_library"   # a submodule in every project
# library_mount = "${ACME_KICAD_LIB}"              # or: one shared checkout per machine
```

**`model_prefix`**: the path `--link-3d` writes in front of a model's file
name. It follows `library_mount` and `model_dir` unless you set it. Setting
it outside `<library_mount>/` is allowed, but `--check-3d` then reports those
paths as `other-var` (or `absolute`).

```toml
model_prefix = "${KIPRJMOD}/acme_kicad_library/packages3d"
```

**`stock_symbol_libraries`**: library names `--migrate-schematic` leaves
alone because they ship with KiCad. Default: `Device`, `power`, `Connector`,
`Connector_Generic`, `Switch`, `Transistor_FET`, `Reference_Voltage`,
`Analog_DAC`, `Analog_ADC`, `MCU_ST_STM32`, `Interface_USB`, `Timer`,
`Regulator_Linear`, `Regulator_Switching`, `Logic`, `Memory_Flash`.

```toml
stock_symbol_libraries = ["Device", "power", "Connector", "Connector_Generic"]
```

## Categories

A category is one symbol library plus one footprint library. In the file,
each category is a key or a table with:

| Field | Required | Meaning |
|---|---|---|
| `key` | yes | What you type after `--category`. Letters, digits, `_` and `-`, not starting with a digit (so menu numbers stay unambiguous) |
| `description` | no | Shown in the menus and written as the library's description in the project tables |
| `name` | no | The library name, if not `<library_prefix><key>` |

The order of the list is the menu order, and `--category 3` picks the third.
Two categories cannot share a key or a library name.

```toml
[[categories]]
key = "ics"
description = "Integrated circuits"

[[categories]]
key = "power"
description = "Power management"

[[categories]]
key = "logic"
name = "acme_74xx"          # an existing library whose name is not <prefix><key>
```

The same in JSON: `"categories": [{"key": "ics", "description": "Integrated
circuits"}, "power", {"key": "logic", "name": "acme_74xx"}]`.

The 13 default categories:

| # | Key | Library | Description |
|---|---|---|---|
| 1 | `connectors` | `lib_connectors` | Connectors, headers, sockets, and interconnects |
| 2 | `passives` | `lib_passives` | Resistors, capacitors, inductors, and other passive components |
| 3 | `semiconductors_discretes` | `lib_semiconductors_discretes` | Diodes, transistors, and other discrete semiconductors |
| 4 | `ics_general` | `lib_ics_general` | General purpose integrated circuits |
| 5 | `power_management` | `lib_power_management` | Power management ICs, regulators, and converters |
| 6 | `mcus_soc` | `lib_mcus_soc` | Microcontrollers, SoCs, and processors |
| 7 | `memory_storage` | `lib_memory_storage` | Memory devices, storage, and flash |
| 8 | `rf_communication` | `lib_rf_communication` | RF components, antennas, and communication modules |
| 9 | `sensors` | `lib_sensors` | Sensors, transducers, and measurement devices |
| 10 | `optoelectronics_displays` | `lib_optoelectronics_displays` | LEDs, displays, optocouplers, and optical components |
| 11 | `electromechanical` | `lib_electromechanical` | Switches, relays, motors, and electromechanical components |
| 12 | `protection` | `lib_protection` | Protection devices, fuses, and ESD protection |
| 13 | `mechanicals_misc` | `lib_mechanicals_misc` | Mechanical parts, hardware, and miscellaneous components |

`--init` in a folder that already holds `<prefix>*` libraries makes those
the categories instead, one per library name. A name whose remainder is not a
valid key keeps its name under a made-up key (`acme_74xx` becomes key
`c_74xx`, name `acme_74xx`).

## Git settings

| Setting | Effect |
|---|---|
| `git_commit = true` | Commit after every command that writes, as if `--commit` were given. A planned import commits exactly the files it wrote; the other commands stage everything under the library root (`git add .`) |
| `git_push = true` | Run `git push` afterwards, as if `--push` were given |
| `git_message_prefix = "parts: "` | Put in front of every commit message the tool writes |

`--no-commit` and `--no-push` switch them off for one run. `--dry-run`,
`--check-3d` (with or without `--fix-3d`) and refused imports never commit
or push. Without `git_push = true` or `--push`, the tool never runs
`git push`.

## Examples

### An existing house style

The library names its libraries `acme_<category>`, keeps models in
`models/`, keeps an old SamacSys export in
`vendor/SamacSys_Parts.3dshapes/`, and every project mounts it as the
submodule `acme_kicad_library`. Commits get a prefix:

```toml
library_prefix = "acme_"
model_dir = "models"
model_search_dirs = ["vendor/SamacSys_Parts.3dshapes"]
library_mount = "${KIPRJMOD}/acme_kicad_library"
git_commit = true
git_message_prefix = "parts: "

[[categories]]
key = "ics"
description = "Integrated circuits"

[[categories]]
key = "power"
description = "Power management"

[[categories]]
key = "protection"
```

`kicad-part-importer part.zip --category power --link-3d --yes` then writes
`lib_sym/acme_power.kicad_sym` and `lib_fp/acme_power.pretty/`, links the
footprints to `${KIPRJMOD}/acme_kicad_library/models/<file>`, and commits as
`parts: Add components from part.zip`. The same file is what `--init`
writes from flags; see
[private-library.md](private-library.md#migrating-an-existing-library) for a
full run.

### Without a file

Every setting except the categories and the stock list also works from the
environment, and most from flags. Here with the default categories:

```bash
export KICAD_PART_IMPORTER_LIBRARY_PREFIX=acme_
export KICAD_PART_IMPORTER_MODEL_DIR=models
kicad-part-importer part.zip --library-mount '${KIPRJMOD}/acme_kicad_library' \
    --category power_management --link-3d --yes
```

Quote `${...}` on the command line so the shell does not expand it.

### Projects next to the library

When projects sit beside the library instead of around it, point
`project_dir` at one of them. The default mount follows:

```text
$ cd ~/work/parts
$ kicad-part-importer --init --project-dir ../boards/board1 | head -n 2
Library root: /tmp/demo/work/parts
✓ Wrote kicad-part-importer.toml: prefix 'lib_', 13 categories, mount ${KIPRJMOD}/../../parts

$ grep -E "^(library_mount|project_dir)" kicad-part-importer.toml
library_mount = "${KIPRJMOD}/../../parts"
project_dir = "../boards/board1"
```

### A template for new libraries

A company can keep one template file and seed every new library from it.
`--init --config TEMPLATE` writes the template's settings into the new
library's own file:

```bash
kicad-part-importer --init --library ~/kicad/new_lib --config ~/acme-template.toml
```

## Validation

Every setting is checked before anything runs. An invalid one is a usage
error (exit code 2) that names the setting:

```text
$ kicad-part-importer --library-mount 'acme_kicad_library' --show-config
✗ library_mount 'acme_kicad_library' must start with a KiCad path variable, e.g. ${KIPRJMOD}/my_kicad_library

$ kicad-part-importer --config /tmp/demo/bad.toml --show-config
✗ config file /tmp/demo/bad.toml: unknown setting(s) library_prefx (known: library_root, library_prefix, symbol_dir, footprint_dir, model_dir, model_search_dirs, project_dir, library_mount, model_prefix, categories, stock_symbol_libraries, git_commit, git_push, git_message_prefix)

$ KICAD_PART_IMPORTER_GIT_PUSH=maybe kicad-part-importer --show-config
✗ KICAD_PART_IMPORTER_GIT_PUSH='maybe': use 1/true/yes/on or 0/false/no/off
```

The rules are: folders must stay inside the library root; the mount must
start with `${VAR}`; library names cannot hold `/ \ : "` or control
characters; category keys must be unique and must not start with a digit;
booleans must be `true` / `false` in a file; lists must be lists of strings.
