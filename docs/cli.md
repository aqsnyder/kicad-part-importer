# Command-line reference

```text
kicad-part-importer [FILE] [options]
```

The option tables and the `--help` text at the end of this page are generated
from the tool's own argument parser (`kicad_part_importer.build_parser()`),
so they list every option, its default and the environment variable that
sets it.

## What a command line does

The tool picks one action from the options you give, in this order:

| You give | It does |
|---|---|
| `--init` | Creates a library: writes `kicad-part-importer.toml` (unless the folder has one) and the folders and empty category libraries. Runs alone |
| `--show-config` | Prints the effective settings as JSON and exits |
| `--check-3d` | Checks (and with `--fix-3d` fixes) every footprint's 3D model path. Never commits |
| `FILE.zip` plus any of `--category`, `--link-3d`, `--verify-3d`, `--yes`, `--dry-run`, `--json`, `--keep-zip`, `--delete-zip`, `--overwrite` | A **planned import**: reads the zip and the library, decides every write, refuses conflicts before writing anything, then writes. Prompts only for what you did not give (the category menu, the delete-zip question), and never with `--yes`, `--dry-run` or `--json` |
| `--init-libraries` | Creates missing folders and empty category libraries (no config file) |
| `--migrate-schematic SCHEMATIC` | Copies the custom parts a schematic uses into the categories and points the schematic at the copies (interactive) |
| `--migrate [FILE.kicad_sym]` | Copies symbols from other symbol libraries into the categories (interactive) |
| `--add-to-project` (alone) | Adds category libraries to the project's library tables (interactive). Never commits: the tables are project files |
| `FILE.zip` alone | The **interactive import**: category menu, copy everything as is, delete-zip question |
| `FILE.kicad_sym` alone | Same as `--migrate FILE.kicad_sym` |

`--add-to-project` together with a zip also adds libraries after the import.
`--add-to-project`, `--migrate` and `--migrate-schematic` always ask
questions, so they are refused together with `--yes`, `--dry-run` or
`--json`.

A prompt that gets no answer, because stdin is closed (a script, CI, an
agent) or you press Ctrl+C, stops the run with exit code 2 and says what to
pass instead (for an import: `--category` and `--yes`). Nothing is written
after that point; a migration first points the schematic at the parts it
already copied. With no answer to "Delete the zip file?" the zip is kept.

Before any command that reads or writes the library, the tool checks that
the library root holds the symbol or footprint folder. If it holds neither,
the command stops with exit code 2 instead of creating a library in the
wrong place (see [troubleshooting](troubleshooting.md#not-a-part-library)).

## Which library

1. `--library DIR` (or its older spelling `--library-root DIR`);
2. `KICAD_PART_IMPORTER_LIBRARY_ROOT`;
3. `library_root` in a config file named with `--config` or
   `KICAD_PART_IMPORTER_CONFIG`;
4. the nearest folder at or above the current directory that holds a
   `kicad-part-importer.toml` or `kicad-part-importer.json` (skipped when a
   config file is named explicitly);
5. the current directory.

`--show-config` reports which one applied as `library_root_source`
(`command line`, `environment`, `config file`, `discovered` or
`current directory`). `--init` never walks up: it creates the library in
`--library DIR` or the current directory.

## Options

### Positional arguments

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `FILE` | - | - | Part zip to import (prompts for the category unless --category is given), or a .kicad_sym file to migrate. |

### Options

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--version` | - | - | Print the version and exit. |

### Commands

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--init` | - | off | Create a library in the library root (--library, else the current directory): write kicad-part-importer.toml from the settings in effect (unless the folder has a config file already), then create the folders and empty category libraries. In a folder that already holds <prefix>* libraries, those become the categories. |
| `--init-libraries` | - | off | Create the folders and the empty category libraries that don't exist yet (no config file). |
| `--add-to-project` | - | off | Add category libraries (asks which) to the project's sym-lib-table and fp-lib-table. |
| `--migrate` | - | off | Copy symbols from FILE, or from every other .kicad_sym in the symbol folder, into the categories (asks for each; the originals stay). |
| `--migrate-schematic SCHEMATIC` | - | - | Copy the custom parts a .kicad_sch uses into the categories and point its references at the copies (asks for each; keeps a .kicad_sch.bak). |
| `--show-config` | - | off | Print the effective settings as JSON and exit. |

### Zip import without prompts (any of these makes the import a planned run)

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--category KEY` | - | - | Category to import into: key (power_management), library name (lib_power_management) or menu number (5). |
| `--link-3d` | - | off | Point each footprint's (model ...) at the library's copy of its model. |
| `--overwrite` | - | refuse | Replace an existing footprint or 3D model whose content differs. |
| `--yes` | - | off | Never prompt; --category is then required. |
| `--dry-run` | - | off | Plan and check only; write nothing, commit nothing (no prompts). |
| `--json` | - | off | Print one JSON report on stdout, logs on stderr (no prompts). |
| `--keep-zip` | - | off | Keep the zip without asking. |
| `--delete-zip` | - | off | Delete the zip after a clean import (kept when the exit code is not 0). |

### 3D models

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--verify-3d` | - | off | Load the imported or checked footprints in KiCad (kicad-cli STEP export) and report every model that does not load. |
| `--kicad-bin DIR` | `KICAD_BIN` | the KiCad 10 / 9 install on Windows, then kicad-cli on PATH | KiCad's bin folder, holding kicad-cli. When given, nothing else is searched. |
| `--check-3d` | - | off | Check every footprint's 3D model path in the category footprint libraries; exit 1 while problems remain. Never commits. |
| `--fix-3d` | - | off | With --check-3d: rewrite fixable paths to the library form (or remove a dead duplicate reference). |
| `--all-footprint-libs` | - | off | With --check-3d: check every .pretty in the footprint folder, not only the category libraries. |

### Library and settings (flags override KICAD_PART_IMPORTER_* variables, which override the config file)

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--library DIR`, `--library-root DIR` | `KICAD_PART_IMPORTER_LIBRARY_ROOT` | the nearest folder at or above the current directory holding a config file, else the current directory | The library root. |
| `--config FILE` | `KICAD_PART_IMPORTER_CONFIG` | - | Config file to read instead of the one in the library root. With --init: a template for the new library. |
| `--config-format {toml,json}` | - | toml when Python can read TOML, else json | Format of the file --init writes. |
| `--library-prefix PREFIX` | `KICAD_PART_IMPORTER_LIBRARY_PREFIX` | lib_ | Name prefix of the category libraries. |
| `--symbol-dir DIR` | `KICAD_PART_IMPORTER_SYMBOL_DIR` | lib_sym | Symbol library folder in the library root. |
| `--footprint-dir DIR` | `KICAD_PART_IMPORTER_FOOTPRINT_DIR` | lib_fp | Footprint library folder in the library root. |
| `--model-dir DIR` | `KICAD_PART_IMPORTER_MODEL_DIR` | 3d_models | 3D model folder in the library root. |
| `--model-search-dir DIR` | `KICAD_PART_IMPORTER_MODEL_SEARCH_DIRS` | none | Another folder in the library root where --fix-3d looks for models; repeat for more. |
| `--library-mount MOUNT` | `KICAD_PART_IMPORTER_LIBRARY_MOUNT` | ${KIPRJMOD}/<path from the project folder to the library root> | How projects reach the library root in model paths, starting with a path variable. |
| `--model-prefix PREFIX` | `KICAD_PART_IMPORTER_MODEL_PREFIX` | <library mount>/<model folder> | Model path --link-3d writes before the file name. |
| `--project-dir DIR` | `KICAD_PART_IMPORTER_PROJECT_DIR` | the folder that holds the library root | Folder holding the project's sym-lib-table / fp-lib-table. |

### Git (default: git_commit / git_push in the config file, else off)

| Option | Environment variable | Default | Description |
|---|---|---|---|
| `--commit` | `KICAD_PART_IMPORTER_GIT_COMMIT` | `git_commit` in the config file, else off | Commit the library files the command wrote, and nothing else. Project files it edits (library tables, schematic) are left to you, and files git ignores are left out and named. --init commits only with this flag. |
| `--no-commit` | - | - | Do not commit, whatever the config file says. |
| `--push` | `KICAD_PART_IMPORTER_GIT_PUSH` | `git_push` in the config file, else off | Run git push afterwards. Never done otherwise; --init pushes only with this flag. |
| `--no-push` | - | - | Do not push, whatever the config file says. |

### Environment variables

| Variable | Setting | Default |
|---|---|---|
| `KICAD_PART_IMPORTER_LIBRARY_ROOT` | `library_root` | nearest folder at or above the current directory holding a config file, else the current directory |
| `KICAD_PART_IMPORTER_LIBRARY_PREFIX` | `library_prefix` | `lib_` |
| `KICAD_PART_IMPORTER_SYMBOL_DIR` | `symbol_dir` | `lib_sym` |
| `KICAD_PART_IMPORTER_FOOTPRINT_DIR` | `footprint_dir` | `lib_fp` |
| `KICAD_PART_IMPORTER_MODEL_DIR` | `model_dir` | `3d_models` |
| `KICAD_PART_IMPORTER_MODEL_SEARCH_DIRS` | `model_search_dirs` | none (list separated by `os.pathsep`: `:` on Linux and macOS, `;` on Windows) |
| `KICAD_PART_IMPORTER_PROJECT_DIR` | `project_dir` | the folder that holds the library root |
| `KICAD_PART_IMPORTER_LIBRARY_MOUNT` | `library_mount` | `${KIPRJMOD}/<path from project_dir to the library root>` |
| `KICAD_PART_IMPORTER_MODEL_PREFIX` | `model_prefix` | `<library_mount>/<model_dir>` |
| `KICAD_PART_IMPORTER_GIT_COMMIT` | `git_commit` | `false` (values: 1/true/yes/on, 0/false/no/off) |
| `KICAD_PART_IMPORTER_GIT_PUSH` | `git_push` | `false` (same values) |
| `KICAD_PART_IMPORTER_GIT_MESSAGE_PREFIX` | `git_message_prefix` | empty |
| `KICAD_PART_IMPORTER_CONFIG` | config file to read (like `--config`) | `kicad-part-importer.toml` / `.json` in the library root |
| `KICAD_BIN` | KiCad's `bin` folder (like `--kicad-bin`) | default KiCad 10 / 9 install on Windows, then `kicad-cli` on `PATH` |

### Full `--help`

```text
$ kicad-part-importer --help
usage: kicad-part-importer [-h] [--version] [--init] [--init-libraries] [--add-to-project]
                           [--migrate] [--migrate-schematic SCHEMATIC] [--show-config]
                           [--category KEY] [--link-3d] [--overwrite] [--yes] [--dry-run] [--json]
                           [--keep-zip] [--delete-zip] [--verify-3d] [--kicad-bin DIR]
                           [--check-3d] [--fix-3d] [--all-footprint-libs] [--library DIR]
                           [--config FILE] [--config-format {toml,json}] [--library-prefix PREFIX]
                           [--symbol-dir DIR] [--footprint-dir DIR] [--model-dir DIR]
                           [--model-search-dir DIR] [--library-mount MOUNT]
                           [--model-prefix PREFIX] [--project-dir DIR] [--commit] [--no-commit]
                           [--push] [--no-push]
                           [FILE]

Import vendor part zips (TI / Ultra Librarian, SamacSys, SnapEDA) into a categorized KiCad library and link every footprint to its 3D model.

positional arguments:
  FILE                  Part zip to import (prompts for the category unless --category is given),
                        or a .kicad_sym file to migrate

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit

commands:
  --init                Create a library in the library root (--library, else the current
                        directory): write kicad-part-importer.toml from the settings in effect
                        (unless the folder has a config file already), then create the folders and
                        empty category libraries. In a folder that already holds <prefix>*
                        libraries, those become the categories
  --init-libraries      Create the folders and the empty category libraries that don't exist yet
                        (no config file)
  --add-to-project      Add category libraries (asks which) to the project's sym-lib-table and fp-
                        lib-table
  --migrate             Copy symbols from FILE, or from every other .kicad_sym in the symbol
                        folder, into the categories (asks for each; the originals stay)
  --migrate-schematic SCHEMATIC
                        Copy the custom parts a .kicad_sch uses into the categories and point its
                        references at the copies (asks for each; keeps a .kicad_sch.bak)
  --show-config         Print the effective settings as JSON and exit

zip import without prompts (any of these makes the import a planned run):
  --category KEY        Category to import into: key (power_management), library name
                        (lib_power_management) or menu number (5)
  --link-3d             Point each footprint's (model ...) at the library's copy of its model
  --overwrite           Replace an existing footprint or 3D model whose content differs (default:
                        refuse)
  --yes                 Never prompt; --category is then required
  --dry-run             Plan and check only; write nothing, commit nothing (no prompts)
  --json                Print one JSON report on stdout, logs on stderr (no prompts)
  --keep-zip            Keep the zip without asking
  --delete-zip          Delete the zip after a clean import (kept when the exit code is not 0)

3D models:
  --verify-3d           Load the imported or checked footprints in KiCad (kicad-cli STEP export)
                        and report every model that does not load
  --kicad-bin DIR       KiCad's bin folder, holding kicad-cli (env KICAD_BIN; default: the KiCad
                        10 / 9 install on Windows, then kicad-cli on PATH). When given, nothing
                        else is searched
  --check-3d            Check every footprint's 3D model path in the category footprint libraries;
                        exit 1 while problems remain. Never commits
  --fix-3d              With --check-3d: rewrite fixable paths to the library form (or remove a
                        dead duplicate reference)
  --all-footprint-libs  With --check-3d: check every .pretty in the footprint folder, not only the
                        category libraries

library and settings (flags override KICAD_PART_IMPORTER_* variables, which override the config file):
  --library DIR, --library-root DIR
                        The library root (env KICAD_PART_IMPORTER_LIBRARY_ROOT; default: the
                        nearest folder at or above the current directory holding a config file,
                        else the current directory)
  --config FILE         Config file to read instead of the one in the library root (env
                        KICAD_PART_IMPORTER_CONFIG; .toml or .json). With --init: a template for
                        the new library
  --config-format {toml,json}
                        Format of the file --init writes (default: toml when Python can read TOML,
                        else json)
  --library-prefix PREFIX
                        Name prefix of the category libraries (env
                        KICAD_PART_IMPORTER_LIBRARY_PREFIX; default: lib_)
  --symbol-dir DIR      Symbol library folder in the library root (env
                        KICAD_PART_IMPORTER_SYMBOL_DIR; default: lib_sym)
  --footprint-dir DIR   Footprint library folder in the library root (env
                        KICAD_PART_IMPORTER_FOOTPRINT_DIR; default: lib_fp)
  --model-dir DIR       3D model folder in the library root (env KICAD_PART_IMPORTER_MODEL_DIR;
                        default: 3d_models)
  --model-search-dir DIR
                        Another folder in the library root where --fix-3d looks for models; repeat
                        for more (env KICAD_PART_IMPORTER_MODEL_SEARCH_DIRS, separated by the OS
                        path separator; default: none)
  --library-mount MOUNT
                        How projects reach the library root in model paths, starting with a path
                        variable (env KICAD_PART_IMPORTER_LIBRARY_MOUNT; default:
                        ${KIPRJMOD}/<path from the project folder to the library root>)
  --model-prefix PREFIX
                        Model path --link-3d writes before the file name (env
                        KICAD_PART_IMPORTER_MODEL_PREFIX; default: <library mount>/<model folder>)
  --project-dir DIR     Folder holding the project's sym-lib-table / fp-lib-table (env
                        KICAD_PART_IMPORTER_PROJECT_DIR; default: the folder that holds the
                        library root)

git (default: git_commit / git_push in the config file, else off):
  --commit              Commit the library files the command wrote, and nothing else (env
                        KICAD_PART_IMPORTER_GIT_COMMIT). Project files it edits (library tables,
                        schematic) are left to you. --init commits only with this flag
  --no-commit           Do not commit, whatever the config file says
  --push                Run git push afterwards (env KICAD_PART_IMPORTER_GIT_PUSH). Never done
                        otherwise; --init pushes only with this flag
  --no-push             Do not push, whatever the config file says

Examples:
  kicad-part-importer --init                         create a library here: config file + folders
  kicad-part-importer --init --library-prefix acme_  ... or describe an existing acme_* library
  kicad-part-importer part.zip                       import with prompts
  kicad-part-importer part.zip --category power_management --link-3d --yes
  kicad-part-importer part.zip --category 5 --link-3d --dry-run --json
  kicad-part-importer --check-3d                     check every footprint's 3D model path
  kicad-part-importer --check-3d --fix-3d --verify-3d --yes
  kicad-part-importer --add-to-project --project-dir ../my_board
  kicad-part-importer --migrate old_parts.kicad_sym
  kicad-part-importer --migrate-schematic ../power.kicad_sch --commit
  kicad-part-importer --show-config

Which library: --library DIR, else $KICAD_PART_IMPORTER_LIBRARY_ROOT, else the
nearest folder at or above the current directory that holds a
kicad-part-importer.toml / .json, else the current directory.
Settings: flags > KICAD_PART_IMPORTER_* variables > that config file > defaults.

Exit codes: 0 ok, 1 failed, 2 usage, 3 refused (nothing written).
Documentation: https://github.com/aqsnyder/kicad-part-importer/tree/main/docs
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | OK |
| 1 | Failed: something you asked for did not happen. A write failed; a 3D model did not load in KiCad, or KiCad could not load a footprint at all; `--check-3d` found problems (with `--fix-3d`: problems it cannot fix); a requested commit or push failed (the files stay written); `--add-to-project` found no project tables; a migration could not copy a part (not found, unreadable, or already in the category) |
| 2 | Usage: bad options or settings, a missing or unsupported input file, a zip that cannot be read (not a zip, cut short, or a file in it that fails its CRC check), an unknown category, `--yes` without `--category`, KiCad not found for `--verify-3d`, the library root is not a library, no answer at a prompt (stdin closed or Ctrl+C) |
| 3 | Refused: a symbol that already exists, a footprint / 3D model that exists with other content, or a vendor file (or one of the library's own symbol libraries) that is not UTF-8 text. Nothing was written |

The codes are the same for every command, the prompting ones included.
`--check-3d --fix-3d --dry-run` exits as if the fixes had been made, so a CI
job can ask "would a fix make this clean?".

## The JSON report

With `--json`, stdout holds exactly one JSON object and every log line goes
to stderr (git's own output included), so `kicad-part-importer ... --json |
jq .` always works. That holds for usage errors too (a missing zip, a bad
setting, an option argparse does not know): the object then has `errors`,
`exit_code` 2 and `ok` false.

```text
$ kicad-part-importer ~/Downloads/missing.zip --category passives --yes --json 2>/dev/null
{
 "command": "import",
 "errors": [
  "file '/tmp/demo/Downloads/missing.zip' not found"
 ],
 "exit_code": 2,
 "ok": false
}
```

For an import, the object has:

| Key | Content |
|---|---|
| `command` | `"import"` |
| `zip`, `library_root` | The paths used |
| `dry_run`, `link_3d` | The options |
| `category` | The category key |
| `symbols` | One row per symbol: `name`, `source` (path in the zip), `target`, `action` (`append` / `refused`), `footprint_field` |
| `footprints` | One row per footprint: `name`, `source`, `target`, `action` (`add` / `replace` / `identical` / `refused`) and, with `--link-3d`, `model`: `before`, `after` (lists of model paths), `action` (`insert` / `rewrite` / `remove` / `keep`), `rule` (why that model was chosen) |
| `models` | One row per 3D model: `name`, `source`, `target`, `action` (`add` / `replace` / `identical` / `refused`) |
| `ignored_files` | Files in the zip that are not symbols, footprints or models |
| `warnings`, `errors` | Lists of messages. A plan error (exit code 3) means nothing was written. An error after the writes (the KiCad check could not run, the project tables were not updated, a requested commit or push failed) leaves `written` as it is. With `--commit`, written files that git ignores are named in `warnings` (`not committed, git ignores them: ...`) |
| `written` | Library-relative paths written (empty on `--dry-run`) |
| `zip_action` | `kept` or `deleted` (absent on `--dry-run` and when the import was refused) |
| `verify_3d` | With `--verify-3d`: `kicad_version`, `checked`, `loaded`, `failed` (rows with `footprint`, `ref`, `model`, `reason`, `body_loaded`), `no_body`, `no_model`, `load_errors` (rows with `footprint`, `error`: footprints KiCad could not load at all, a failure like `failed`), `log` |
| `exit_code`, `ok` | The exit code, and whether it is 0 |

For `--check-3d`: `command` (`"check-3d"`), `library_root`, `dry_run`,
`footprints` (how many were checked), `counts` (model references by kind),
`problems`, `fixable`, `unfixable` (rows with `footprint`, `ref`, `kind`,
`fix`, `fix_action`), `changed` (with `--fix-3d`), `verify_3d`, `exit_code`
and `ok`. A real example is in [3d-models.md](3d-models.md#machine-readable-output).
