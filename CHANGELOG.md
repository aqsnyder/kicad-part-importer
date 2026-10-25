# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-25

Initial public release.

### Added

- Import vendor part zips (TI / Ultra Librarian, SamacSys / Component Search
  Engine and SnapEDA layouts) into a categorized KiCad library: one symbol
  library and one footprint library per category, plus a shared 3D model
  folder. Thirteen general electronics categories by default.
- Planned, prompt-free import (`--category`, `--yes`, `--dry-run`, `--json`)
  that prints its plan, decides every write first and refuses, before writing
  anything, a duplicate symbol or a footprint / model that exists with other
  content (`--overwrite` to replace). The interactive import (category menu,
  then the delete-zip question) is kept for quick use.
- `--link-3d`: point each footprint's `(model ...)` at the library's copy of
  its model through the library mount, choosing the model by name,
  density-variant suffix or prefix, and keeping offset, scale and rotation.
- `--check-3d` / `--fix-3d`: classify every model path in the category
  footprint libraries (ok, case, missing, bare, absolute, other-var, stock)
  and rewrite the fixable ones; a dead duplicate reference is removed rather
  than rewritten.
- `--verify-3d`: load the touched footprints in KiCad (`kicad-cli pcb export
  step` with KiCad's Python) and report every model that does not load,
  including on `--dry-run` through a staged copy.
- Library discovery: the library root comes from `--library`,
  `KICAD_PART_IMPORTER_LIBRARY_ROOT`, or the nearest folder at or above the
  current directory holding `kicad-part-importer.toml` / `.json` (as git finds
  `.git`), else the current directory. Commands refuse a folder that is not a
  library.
- `--init`: create a library and write its starter config file (prefix,
  folders, mount, git settings, categories), or describe an existing library,
  whose `<prefix>*` libraries become the categories. `--init --config
  TEMPLATE` seeds a new library from a template.
- Per-library configuration through a TOML or JSON file, `KICAD_PART_IMPORTER_*`
  environment variables and flags: category prefix, categories and
  descriptions, symbol / footprint / model folders, extra model search
  folders, library mount and model path prefix, project folder, stock symbol
  libraries, and git behaviour (`git_commit`, `git_push`,
  `git_message_prefix`). `--show-config` prints the result and where the
  library root came from.
- Project integration (`--add-to-project`, writing entries through the
  library mount with the category descriptions, and skipping libraries
  already listed), library initialization (`--init-libraries`), and
  migration from older symbol libraries and schematics (`--migrate`,
  `--migrate-schematic`).
- Optional git integration: `--commit` / `--no-commit` (a planned import
  commits only the files it wrote) and `--push` / `--no-push`; the tool never
  pushes unless asked. `--dry-run` and `--check-3d` never commit.
- Exit codes 0 (ok), 1 (failed), 2 (usage), 3 (refused, nothing written), and
  a machine-readable JSON report with `--json`; git's own output goes to
  stderr there.

[Unreleased]: https://github.com/aqsnyder/kicad-part-importer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aqsnyder/kicad-part-importer/releases/tag/v0.1.0
