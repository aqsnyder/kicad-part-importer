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
  whose `<prefix>*` libraries become the categories (the default ones keep
  their descriptions and menu order). `--init --config TEMPLATE` seeds a new
  library from a template.
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
- Optional git integration: `--commit` / `--no-commit` (every command commits
  only the library files it wrote) and `--push` / `--no-push`; the tool never
  pushes unless asked. `--dry-run` and `--check-3d` never commit.
- Exit codes 0 (ok), 1 (failed), 2 (usage), 3 (refused, nothing written), and
  a machine-readable JSON report with `--json`; git's own output goes to
  stderr there.

### Fixed

Fixed before the v0.1.0 tag (found in review of the first public commits);
each has a regression test.

- `--json` prints exactly one JSON object on stdout for usage and settings
  errors too (no zip, a missing zip, `--keep-zip` with `--delete-zip`, a
  prompting command, a bad setting, an unknown option), with exit code 2.
- A prompt with no answer (stdin closed, or Ctrl+C) no longer ends in a
  traceback: the run stops with exit code 2 and says what to pass instead.
  With no answer to "Delete the zip file?" the zip is kept.
- Exit codes are the same on every path: a requested action that fails exits
  1 (`--add-to-project` without project tables, a migration that could not
  copy a part, `--init-libraries`, the interactive import, a failed
  `--commit` or `--push`, which the JSON report now lists in `errors`); a
  missing or unsupported input file, a zip that cannot be read (not a zip,
  cut short, or a file in it that fails its CRC check), or nothing to do,
  exits 2. An unreadable zip used to exit 1 in the interactive import and
  end in a traceback in the planned one when a file in it was damaged.
- `--commit` commits only the library files the command wrote (`git add --`
  / `git commit --` with those paths), never other changes the user had
  staged; a run that wrote nothing commits nothing. A written file that git
  ignores (a model folder in `.gitignore`, say) is left out of the commit
  and named, in the JSON report's `warnings` too, and the other files are
  committed (`git add` fails on an ignored file, so in such a library the
  commit failed and committed nothing). Project files
  (`--add-to-project`'s tables, the schematic `--migrate-schematic` rewrites)
  are never committed, and `--add-to-project` says that `--commit` does not
  apply to it.
- `--init` commits and pushes only with `--commit` / `--push` on its command
  line: `git_commit = true` in a template or the environment no longer makes
  it commit the user's edits, or fail in a folder that is not a repository.
- `--init --config TEMPLATE` writes every setting the template names,
  `model_prefix` and `project_dir` included (they were commented out).
- `--init` on a library that uses the default names keeps those categories'
  descriptions and menu order (so `--category N` keeps its meaning) and adds
  unknown libraries after them.
- `--check-3d` compares the letter case of every folder in a model path, not
  only the file name, so `3D_Models/X.step` for `3d_models/X.step` is
  `case` (fixable) instead of `ok` on Windows / macOS and `missing` on Linux.
  A model it finds for a bare or absolute path is pointed at the model
  folder as spelled on disk, not as `model_dir` spells it.
- `--check-3d` also checks a category whose library `name` lacks
  `library_prefix`, and the import's "also exists in" warnings look there
  too.
- `--verify-3d` treats a footprint KiCad cannot load as a failure: `--check-3d`
  exits 1, and both commands name it and count it in the summary.
- `--migrate` shows and copies the symbol under its own name (not its last
  unit's), finds the footprint a `library:footprint` field names (in
  `<library>.pretty` first), says "Copied" (the original stays), and never
  appends a symbol the category library already holds.
- `--migrate-schematic` rewrites only the references of parts whose symbol it
  copied (a part it left alone keeps its Footprint field even when it uses
  the same footprint as a part it copied), keeps the Footprint field of a
  footprint it could not copy, counts only real migrations and never appends
  a duplicate symbol.
- Files keep their line endings on Windows: `--migrate-schematic` writes the
  schematic with its own line endings and copies footprints byte for byte,
  and `--init` writes new symbol libraries with LF.
- A vendor file that is not UTF-8 text, or a category symbol library of the
  library itself that is not, is a plan error (exit code 3, with the JSON
  report) instead of a traceback.
- docs/private-library.md creates the repository with `git init -b main`, so
  the `git push -u origin main` that follows works where the default branch
  is `master`.

[Unreleased]: https://github.com/aqsnyder/kicad-part-importer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/aqsnyder/kicad-part-importer/releases/tag/v0.1.0
