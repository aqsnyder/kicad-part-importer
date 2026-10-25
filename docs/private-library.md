# Using the tool with a private company library

The tool and the library are separate projects. The tool (this repository)
is public and knows nothing about any company. The library, with its parts,
naming conventions and settings file, can live in a private repository.
Nobody has to fork the tool to use it with their own conventions.

```
github.com/aqsnyder/kicad-part-importer      public: the tool, installed with pip
git.example.com/acme/acme_kicad_library      private: your parts + kicad-part-importer.toml
git.example.com/acme/<each board project>    private: mounts the library (submodule) and its tables
```

- [1. Describe the library in its own config file](#1-describe-the-library-in-its-own-config-file)
- [2. Install the public tool, pinned to a release](#2-install-the-public-tool-pinned-to-a-release)
- [3. Daily work](#3-daily-work)
- [4. Git behaviour per library](#4-git-behaviour-per-library)
- [A CI check for the library](#a-ci-check-for-the-library)
- [Migrating an existing library](#migrating-an-existing-library)
- [What stays private](#what-stays-private)

## 1. Describe the library in its own config file

Create the private repository and let `--init` write the settings file. For
a new library:

```bash
mkdir acme_kicad_library && cd acme_kicad_library
git init
kicad-part-importer --init --library-prefix acme_ \
    --library-mount '${KIPRJMOD}/acme_kicad_library'
git add -A && git commit -m "New part library"
git remote add origin https://git.example.com/acme/acme_kicad_library.git
git push -u origin main
```

Then edit `kicad-part-importer.toml` to make it yours: the category list and
descriptions, the git behaviour and the commit-message prefix. Commit the
change. Every setting is described in [configuration.md](configuration.md).
From now on everyone who clones the library gets the same behaviour,
because the tool reads the file from the library itself (it walks up from
the current directory to find it).

For an existing library, see [Migrating an existing library](#migrating-an-existing-library)
below.

## 2. Install the public tool, pinned to a release

Pin the tool to a release tag so that everyone, and CI, runs the same
version:

```bash
pip install "git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0"
# or, isolated from other Python packages:
pipx install "git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0"
```

A requirements file in the library repository makes it one command for new
team members:

```text
# requirements-tools.txt (in the private library repository)
kicad-part-importer @ git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0
```

```bash
pip install -r requirements-tools.txt
```

To upgrade, change the tag in one place, run the checks below, and merge.
The [changelog](../CHANGELOG.md) lists what changed between releases.

## 3. Daily work

```bash
cd ~/kicad/acme_kicad_library            # or the submodule inside a project
git switch -c parts/demo-tvs
kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --dry-run
kicad-part-importer ~/Downloads/LIB_DEMOTVS5.zip --category protection --link-3d --yes
kicad-part-importer --check-3d
git push -u origin parts/demo-tvs         # open a pull request; CI runs the check
```

The planned import refuses, before writing anything, a symbol that already
exists and a footprint or model that exists with other content. A reviewer
therefore only has to look at new files and appended symbols.

## 4. Git behaviour per library

Commit and push behaviour belongs to the library, not to each person's
habits. With this in the library's file:

```text
$ grep ^git_ kicad-part-importer.toml
git_commit = true
git_push = false
git_message_prefix = "parts: "
```

every import commits exactly the files it wrote, with the prefix:

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category power --link-3d --yes | tail -n 3
 create mode 100644 lib_fp/acme_power.pretty/PKG0006A-MFG.kicad_mod
 create mode 100644 models/PKG0006A.stp
✓ Committed 5 file(s): parts: Add components from ul_DEMOBUCK1.zip

$ git log --format=%s
parts: Add components from ul_DEMOBUCK1.zip
Describe the library for kicad-part-importer; fix 3D model paths
Existing library
```

A dry run never commits, even with `--commit` or `git_commit = true`:

```text
$ kicad-part-importer ~/Downloads/ul_DEMOBUCK1.zip --category ics --link-3d --dry-run --commit | tail -n 2; git log -1 --format=%s
⚠ footprint PKG0006A-MFG also exists in acme_power.pretty
Dry run: nothing written.
parts: Add components from ul_DEMOBUCK1.zip
```

`--no-commit` and `--no-push` switch the settings off for one run.
`git_push = true` pushes after every write. Most teams leave it off and push
through pull requests.

## A CI check for the library

`--check-3d` needs no KiCad and exits 1 when any footprint's model path is
wrong, so it can gate every pull request to the library. Add `--verify-3d`
where KiCad is installed to prove that every model loads. The workflow below
is a template for the private library repository (GitHub Actions; the steps
are the same on any CI). It installs the public tool at a pinned tag, so it
needs no access tokens.

```yaml
# .github/workflows/library-check.yml in the private library repository
name: library check
on: [push, pull_request]

jobs:
  paths:
    # Fast: no KiCad. Fails on bare, absolute, other-var, wrong-case and missing model paths.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0"
      - run: kicad-part-importer --check-3d

  kicad:
    # Slower: loads every footprint in KiCad and fails on any model that does not load.
    # Adjust the PPA to the KiCad version your team uses.
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          sudo add-apt-repository --yes ppa:kicad/kicad-10.0-releases
          sudo apt-get update
          sudo apt-get install --yes --no-install-recommends kicad
      - run: |
          # --system-site-packages lets the tool import KiCad's pcbnew module
          python3 -m venv --system-site-packages .venv
          .venv/bin/pip install "git+https://github.com/aqsnyder/kicad-part-importer@v0.1.0"
          .venv/bin/kicad-part-importer --check-3d --verify-3d
```

Locally, the first job is just this (exit code 1 means the pull request needs
work):

```text
$ kicad-part-importer --check-3d
Footprints checked: 3; model references: absolute 1, bare 1, ok 1
  bare      lib_fp/acme_connectors.pretty/HDR_DEMO.kicad_mod: HDR_DEMO.step
  absolute  lib_fp/acme_power.pretty/REG_DEMO.kicad_mod: /opt/old-kicad/SamacSys_Parts.3dshapes/DEMOREG.stp  -> ${KIPRJMOD}/acme_kicad_library/vendor/SamacSys_Parts.3dshapes/DEMOREG.stp
```

`--check-3d --json` gives a machine-readable report for annotations
([3d-models.md](3d-models.md#machine-readable-output)).

## Migrating an existing library

Say you already have a library: libraries named `acme_*`, models in
`models/`, an old SamacSys Library Loader export in
`vendor/SamacSys_Parts.3dshapes/`, and footprints whose model paths point all
over the place:

```text
$ ls lib_sym lib_fp
lib_fp:
acme_74xx.pretty
acme_connectors.pretty
acme_ics.pretty
acme_power.pretty

lib_sym:
acme_74xx.kicad_sym
acme_connectors.kicad_sym
acme_ics.kicad_sym
acme_power.kicad_sym
```

Run `--init` in the library with your conventions. It finds the existing
`acme_*` libraries and makes them the categories. It never rewrites an
existing library; it only creates what is missing:

```text
$ kicad-part-importer --init --library-prefix acme_ --model-dir models --model-search-dir vendor/SamacSys_Parts.3dshapes --library-mount '${KIPRJMOD}/acme_kicad_library'
Library root: /tmp/demo/acme/acme_kicad_library
Found 4 existing libraries named acme_*; they become the categories: c_74xx, connectors, ics, power
✓ Wrote kicad-part-importer.toml: prefix 'acme_', 4 categories, mount ${KIPRJMOD}/acme_kicad_library
Initializing library files...
  - Symbol library already exists: acme_74xx.kicad_sym
  - Symbol library already exists: acme_connectors.kicad_sym
  - Symbol library already exists: acme_ics.kicad_sym
  - Symbol library already exists: acme_power.kicad_sym
  - Footprint directory already exists: acme_74xx.pretty
  - Footprint directory already exists: acme_connectors.pretty
  - Footprint directory already exists: acme_ics.pretty
  - Footprint directory already exists: acme_power.pretty
✓ Library initialization complete
```

The file it wrote (comments trimmed):

```toml
library_prefix = "acme_"
symbol_dir = "lib_sym"
footprint_dir = "lib_fp"
model_dir = "models"
model_search_dirs = ["vendor/SamacSys_Parts.3dshapes"]
library_mount = "${KIPRJMOD}/acme_kicad_library"
# model_prefix = "${KIPRJMOD}/acme_kicad_library/models"
# project_dir = ".."
git_commit = false
git_push = false
git_message_prefix = ""
stock_symbol_libraries = [
    "Device", "power", "Connector", "Connector_Generic", "Switch", "Transistor_FET",
    "Reference_Voltage", "Analog_DAC", "Analog_ADC", "MCU_ST_STM32", "Interface_USB", "Timer",
    "Regulator_Linear", "Regulator_Switching", "Logic", "Memory_Flash",
]

[[categories]]
key = "c_74xx"
name = "acme_74xx"

[[categories]]
key = "connectors"

[[categories]]
key = "ics"

[[categories]]
key = "power"
```

`acme_74xx` cannot become the key `74xx`, because a key must not start with a
digit, so it got the key `c_74xx` and keeps its library name. Rename the key
(for example to `logic`), add descriptions and reorder the categories as you
like. The library names do not change.

Check the model paths, fix what can be fixed, and commit:

```text
$ kicad-part-importer --check-3d
Footprints checked: 3; model references: absolute 1, bare 1, ok 1
  bare      lib_fp/acme_connectors.pretty/HDR_DEMO.kicad_mod: HDR_DEMO.step
  absolute  lib_fp/acme_power.pretty/REG_DEMO.kicad_mod: /opt/old-kicad/SamacSys_Parts.3dshapes/DEMOREG.stp  -> ${KIPRJMOD}/acme_kicad_library/vendor/SamacSys_Parts.3dshapes/DEMOREG.stp

$ kicad-part-importer --check-3d --fix-3d --yes
Footprints checked: 3; model references: absolute 1, bare 1, ok 1
  bare      lib_fp/acme_connectors.pretty/HDR_DEMO.kicad_mod: HDR_DEMO.step
  absolute  lib_fp/acme_power.pretty/REG_DEMO.kicad_mod: /opt/old-kicad/SamacSys_Parts.3dshapes/DEMOREG.stp  -> ${KIPRJMOD}/acme_kicad_library/vendor/SamacSys_Parts.3dshapes/DEMOREG.stp
Changed 1 footprint file(s): 1 path(s) rewritten, 0 dead duplicate reference(s) removed

$ git add -A && git commit -q -m "Describe the library for kicad-part-importer; fix 3D model paths" && git log --format=%s
Describe the library for kicad-part-importer; fix 3D model paths
Existing library
```

The absolute path was rewritten to the copy in the search folder.
`HDR_DEMO.step` is in no folder of the library, so it stays reported until
someone adds the model. Once `--check-3d` exits 0, turn on the CI check.

Other migration helpers:

- `--migrate old_parts.kicad_sym` walks the symbols of another symbol
  library, asks for each one's category, and copies the footprint it names
  along.
- `--migrate-schematic board.kicad_sch` finds the custom parts a schematic
  uses (skipping KiCad's stock libraries and libraries that already carry
  your prefix), copies them into the categories, and rewrites the
  schematic's references (it keeps a `.kicad_sch.bak`).
- `--add-to-project` adds the categories to each project's tables, through
  the mount.

### A template for every new library

If the company keeps more than one library, keep one template config (for
example in an internal tools repository) and seed each new library from it.
The template's categories, prefix, mount and git settings become the new
library's own file:

```bash
kicad-part-importer --init --library ~/kicad/new_lib --config ~/acme-tools/kicad-part-importer.toml
```

## What stays private

- **Your parts and conventions.** Names, categories, descriptions, mount and
  git policy live in your library's `kicad-part-importer.toml`. The tool has
  only generic defaults and never reads anything outside the library you
  point it at (and the zip you give it).
- **No network access.** The tool does not download parts or contact any
  server. Git runs only for `--commit` / `--push` or the `git_*` settings,
  against your own remote.
- **No fork needed.** If you need behaviour the settings do not cover, open
  an issue or a pull request for a generic option on the public repository,
  so other users get it too.
