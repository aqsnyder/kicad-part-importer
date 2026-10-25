# kicad-part-importer documentation

kicad-part-importer turns the part downloads you get from component vendors
and CAD-model sites (TI / Ultra Librarian, SamacSys / Component Search Engine,
SnapEDA) into one categorized KiCad library, and keeps every footprint pointed
at its 3D model. It is one command, written in standard-library Python, with a
JSON mode and exit codes for scripts and CI.

The tool is separate from any part library. It works on whichever library you
point it at, and each library carries its own settings file
(`kicad-part-importer.toml`). A company can therefore use the public tool and
keep its part library and naming conventions private.

## Pages

| Page | What it covers |
|---|---|
| [Getting started](getting-started.md) | Install, create a library, import a first part, add the library to a KiCad project |
| [Command-line reference](cli.md) | Every option, its default and its environment variable, generated from the tool's own argument parser |
| [Configuration](configuration.md) | How the tool finds the library, the config file, every setting with type, default and example |
| [Vendor formats](vendor-formats.md) | The zip layouts the importer understands and what it takes from each |
| [3D models](3d-models.md) | `--link-3d`, `--check-3d`, `--fix-3d` and `--verify-3d`, with before/after output |
| [KiCad integration](kicad-integration.md) | `sym-lib-table` / `fp-lib-table`, `${KIPRJMOD}` and `${VAR}` mounts, submodules |
| [Private company library](private-library.md) | Using the public tool with a private library: config file, pinned install, CI check, migrating an existing library |
| [Troubleshooting and FAQ](troubleshooting.md) | Every error message, what it means and what to do |

## How the examples were made

The command output on these pages is real output, trimmed where it repeats.
Most of it comes from Python 3.12 on Linux in a scratch folder under
`/tmp/demo`. The `--verify-3d` runs used KiCad 10.0.7 on Windows. The vendor
zips in the examples are small synthetic files with the same layouts as real
downloads, under made-up part names (`DEMOTVS5`, `DEMOBUCK1`, `DEMOLDO-33`,
`DEMOCAP`). The test suite builds the same kind of zips, so no vendor files
are redistributed here.

## In one minute

```bash
pip install git+https://github.com/aqsnyder/kicad-part-importer
cd my_project/my_kicad_library
kicad-part-importer --init                      # config file + empty category libraries
kicad-part-importer ~/Downloads/LIB_PART.zip --category protection --link-3d --yes
kicad-part-importer --check-3d                  # every footprint's 3D model path is valid
kicad-part-importer --add-to-project            # add the libraries to the project's tables
```
