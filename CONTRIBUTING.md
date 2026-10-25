# Contributing

Thanks for helping. Bug reports, vendor zips that the importer gets wrong
(described, or rebuilt with made-up names; please do not attach vendor
files), documentation fixes and pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/aqsnyder/kicad-part-importer
cd kicad-part-importer
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[test]"
kicad-part-importer --version
```

The tool is four modules at the repository root: `kicad_part_importer.py`
(command line, imports, migration), `kicad_lib_config.py` (settings and
discovery), `kicad_lib_3d.py` (model paths, checks, fixes, finding KiCad) and
`kicad_lib_verify.py` (the script that runs under KiCad's Python for
`--verify-3d`).

## Tests

```bash
python -m pytest                              # or: python -m unittest discover -s tests -v
```

The tests build every fixture they use (synthetic vendor-style zips, a
scratch library per test) in temporary folders, and need no network.

- **KiCad tests** (`tests/test_kicad_verify.py`) run when KiCad is found and
  are skipped otherwise. Point at an install with
  `KICAD_BIN=<KiCad bin folder>`. To prove the suite passes *without* KiCad
  on a machine that has it, hide it: `KICAD_BIN=/nonexistent python -m pytest`.
  `KICAD_BIN` is authoritative, so nothing else is searched.
- **Git tests** use a recorder in place of git, plus one test against a real
  temporary repository (skipped when git is missing).
- CI runs the suite on Linux and Windows with Python 3.9 and 3.12
  (`.github/workflows/tests.yml`), with KiCad hidden.

Please add a test with every behaviour change. A command-line test runs the
tool in a subprocess (`libtest_helpers.run_importer`) on a library made by
`libtest_helpers.make_library`.

## Style

- Standard library only. `tomli` on Python < 3.11 is the one dependency. A new
  dependency needs a very good reason.
- Python 3.9 compatible syntax; lines up to 120 characters; four-space
  indents; LF line endings (`.gitattributes` enforces this).
- Keep the guarantees users rely on: a planned import decides every write
  before making one and refuses conflicts; `--dry-run` writes nothing;
  `--json` keeps stdout to one JSON object; the tool never pushes unless told
  to; files keep their line endings.
- Nothing company- or library-specific in the code. Anything one library might
  want differently from another belongs in a setting
  ([docs/configuration.md](docs/configuration.md)).
- Messages are plain sentences that say what to do next.

## Documentation

User-visible changes need a docs update in `docs/` and an entry under
*Unreleased* in [CHANGELOG.md](CHANGELOG.md). Output shown in the docs must
be real output from a run (trimmed is fine), never typed by hand. The option
tables in `docs/cli.md` mirror `build_parser()`, so update them when you add
or change an option.

## Pull requests

1. Fork, and branch from `main`.
2. Make the change with its tests and docs.
3. Run `python -m pytest` (with and without KiCad if you have it).
4. Open the pull request with a short description of the problem and the
   fix. Small, focused pull requests are reviewed fastest.

By contributing you agree that your contribution is licensed under the MIT
license of this project.
