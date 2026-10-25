"""3D-model handling for kicad-part-importer (used by kicad_part_importer.py).

Standard library only. Three jobs:

1. Link a footprint to its 3D model: rewrite (or insert) the footprint's
   ``(model ...)`` path so it points at the library's model folder through the
   library mount, ``<library_mount>/<model_dir>/<file>`` (by default
   ``${KIPRJMOD}/<library folder>/3d_models/<file>``). That is the form that
   resolves when the library is mounted inside a project (for example as a git
   submodule). A bare file name (the form SamacSys ships) resolves against the
   project folder, not the model folder, so KiCad reports "File not found" for it.
2. Check the whole library: classify every model reference and plan fixes for
   the ones that point at a file that is in the model folder under another path.
3. Run the KiCad check (``kicad_lib_verify.py`` under KiCad's own Python)
   that loads footprints into a throwaway board and exports STEP, which is
   how kicad-cli reports models it cannot load.

All edits are text edits on the footprint file: only the model path token is
replaced (offset / scale / rotate are kept), or one model block is inserted
before the footprint's closing parenthesis. Line endings are preserved.

Functions that need the library layout take ``library``: a
:class:`kicad_lib_config.LibraryConfig`, or a library root path (which then
uses the default layout).
"""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import kicad_lib_config as libcfg

MODEL_EXTENSIONS = (".step", ".stp", ".stpz", ".wrl", ".wrz", ".igs", ".iges")

# The path token after "(model": a quoted string (with escapes) or a bare token.
_MODEL_TOKEN_RE = re.compile(r'\(model\s+("(?:[^"\\]|\\.)*"|[^\s()]+)')
# Density / variant suffixes vendors append to one land pattern
# (Ultra Librarian -L/-M/_L/_M/_N, TI -IPC_A/B/C and -MFG).
_VARIANT_SUFFIX_RE = re.compile(r"(?i)[-_](?:L|M|N|IPC_[ABC]|MFG)$")
_STOCK_VAR_RE = re.compile(r"^\$\{KICAD\d*_3DMODEL_DIR\}")
PROBLEM_KINDS = ("missing", "case", "bare", "absolute", "other-var")


def is_model_file(path):
    """True for 3D model files, by extension only (a vendor readme with '3d' in
    its name is not a model)."""
    return str(path).lower().endswith(MODEL_EXTENSIONS)


def eol_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def read_text(path):
    """Read a KiCad text file without newline translation."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write_text(path, text):
    """Write a KiCad text file without newline translation (keeps its EOLs)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def _unquote(token):
    if token.startswith('"') and token.endswith('"') and len(token) >= 2:
        return re.sub(r"\\(.)", r"\1", token[1:-1])
    return token


def _quote(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def model_refs(fp_text):
    """The (model ...) paths in a footprint, unquoted, in file order."""
    return [_unquote(m.group(1)) for m in _MODEL_TOKEN_RE.finditer(fp_text)]


def footprint_name(fp_text):
    """The name a .kicad_mod declares in its (footprint "X" / (module "X" head."""
    m = re.match(r'\s*\((?:footprint|module)\s+("(?:[^"\\]|\\.)*"|[^\s()]+)', fp_text)
    return _unquote(m.group(1)) if m else None


def model_basename(ref):
    return re.split(r"[\\/]", ref)[-1]


def model_ref_for(file_name, prefix):
    """The (model ...) path for a file in the model folder: ``<prefix>/<file_name>``."""
    return prefix.rstrip("/") + "/" + file_name


def _model_block(path, eol, tabs):
    if tabs:
        lines = ['\t(model %s' % _quote(path), "\t\t(offset", "\t\t\t(xyz 0 0 0)", "\t\t)",
                 "\t\t(scale", "\t\t\t(xyz 1 1 1)", "\t\t)", "\t\t(rotate", "\t\t\t(xyz 0 0 0)", "\t\t)", "\t)"]
    else:
        lines = ["  (model %s" % _quote(path), "    (offset (xyz 0 0 0))", "    (scale (xyz 1 1 1))",
                 "    (rotate (xyz 0 0 0))", "  )"]
    return eol.join(lines) + eol


def set_model_path(fp_text, new_path, replace=None):
    """Point the footprint at ``new_path``.

    replace: None -> rewrite every existing (model ...) path; otherwise a
    callable(old_path) -> bool choosing which ones to rewrite. When the
    footprint has no (model ...) at all, one block with zero offset/rotation
    and unit scale is inserted before the closing parenthesis.
    Returns (new_text, action) with action in {"insert", "rewrite", "keep"}.
    """
    found = list(_MODEL_TOKEN_RE.finditer(fp_text))
    if not found:
        end = fp_text.rstrip().rfind(")")
        if end < 0:
            raise ValueError("not a footprint: no closing parenthesis")
        eol = eol_of(fp_text)
        tabs = "\n\t(" in fp_text
        head = fp_text[:end]
        if not head.endswith(("\n", "\r")):
            head += eol
        return head + _model_block(new_path, eol, tabs) + fp_text[end:], "insert"
    out, last, changed = [], 0, False
    for m in found:
        old = _unquote(m.group(1))
        if (replace is None or replace(old)) and old != new_path:
            out.append(fp_text[last:m.start(1)])
            out.append(_quote(new_path))
            last = m.end(1)
            changed = True
    out.append(fp_text[last:])
    return "".join(out), ("rewrite" if changed else "keep")


def _block_end(text, start):
    """Index just past the parenthesis that closes the block opening at ``start``."""
    depth, i, n = 0, start, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced (model ...) block")


def remove_model_block(fp_text, path):
    """Remove every (model ...) block whose path is ``path``, with its own
    line(s) when it sits on lines of its own. Returns the new text."""
    for m in reversed(list(_MODEL_TOKEN_RE.finditer(fp_text))):
        if _unquote(m.group(1)) != path:
            continue
        start, end = m.start(), _block_end(fp_text, m.start())
        line_start = max(fp_text.rfind("\n", 0, start), fp_text.rfind("\r", 0, start)) + 1
        if not fp_text[line_start:start].strip():
            start = line_start
            rest = fp_text[end:]
            stripped = rest.lstrip(" \t")
            if stripped.startswith("\r\n"):
                end += len(rest) - len(stripped) + 2
            elif stripped.startswith("\n"):
                end += len(rest) - len(stripped) + 1
        fp_text = fp_text[:start] + fp_text[end:]
    return fp_text


def fix_ref(fp_text, old, fix):
    """Point the (model ...) whose path is ``old`` at ``fix``. When another block
    of the footprint already names ``fix``, the ``old`` block is a dead
    duplicate: remove it instead (rewriting it would give the part two
    coincident bodies in 3D view and STEP). Returns (new_text, action) with
    action in {"rewrite", "remove", "keep"}."""
    if fix in [r for r in model_refs(fp_text) if r != old]:
        new = remove_model_block(fp_text, old)
        return new, ("remove" if new != fp_text else "keep")
    return set_model_path(fp_text, fix, replace=lambda o: o == old)


def variant_base(stem):
    """'PKG0005A-IPC_B' -> 'PKG0005A', 'SMA_DIO-L' -> 'SMA_DIO', 'PKG0006A_N' -> 'PKG0006A'."""
    return _VARIANT_SUFFIX_RE.sub("", stem)


def match_model(fp_stem, refs, model_names):
    """Pick the model file (from ``model_names``) for one footprint.

    Order: a model the footprint already names (by file name, any path form,
    case-insensitive); the only model offered; a model whose stem equals the
    footprint's stem without its density suffix; the unique longest model stem
    that prefixes the footprint stem. Returns (name or None, rule).
    """
    if not model_names:
        return None, "no model offered"
    by_lower = {n.lower(): n for n in model_names}
    for r in refs:
        hit = by_lower.get(model_basename(r).lower())
        if hit:
            return hit, "named by footprint"
    if len(model_names) == 1:
        return model_names[0], "only model"
    stems = {n: os.path.splitext(n)[0].upper() for n in model_names}
    base = variant_base(fp_stem).upper()
    exact = [n for n, s in stems.items() if s == base or s == fp_stem.upper()]
    if len(exact) == 1:
        return exact[0], "same stem"
    pref = [(len(s), n) for n, s in stems.items() if fp_stem.upper().startswith(s)]
    if pref:
        pref.sort(reverse=True)
        if len(pref) == 1 or pref[0][0] != pref[1][0]:
            return pref[0][1], "stem prefix"
    return None, "ambiguous: %s" % ", ".join(sorted(model_names))


def classify_ref(ref, library):
    """Classify one (model ...) path against the library.

    Returns (kind, detail). kind is one of:
      ok        -> mount form and the file exists in the library
      case      -> mount form, the file exists but with other letter case in
                   its name or in a folder of its path (loads on Windows and
                   macOS, not on Linux)
      missing   -> mount form but no such file
      stock     -> ${KICADn_3DMODEL_DIR}/... (KiCad's own models; not checked)
      bare      -> file name only (resolves against the project folder)
      absolute  -> drive-letter, UNC or / path (machine-specific)
      other-var -> another ${VAR}/... path
    detail is the library-relative path of the file to point at (the real
    spelling in the library), or None.
    """
    cfg = libcfg.as_config(library)
    root = Path(cfg.library_root)
    mount = cfg.library_mount + "/"
    if ref.startswith(mount):
        rel = ref[len(mount):]
        # Every folder of the path counts, not only the file name: on Windows and
        # macOS "3D_Models/X.step" opens "3d_models/X.step", on Linux it does not.
        real = real_path_in(root, rel)
        if real is None:
            return "missing", None
        same = real == "/".join(p for p in rel.split("/") if p not in ("", "."))
        return ("ok", rel) if same else ("case", real)
    if _STOCK_VAR_RE.match(ref):
        return "stock", None
    name = model_basename(ref)
    if ref.startswith("${"):
        kind = "other-var"
    elif re.match(r"^([A-Za-z]:|[\\/])", ref):
        kind = "absolute"
    elif "/" in ref or "\\" in ref:
        kind = "other-var"  # relative path with directories; treated like other-var
    else:
        kind = "bare"
    return kind, find_model_in_library(name, cfg)


def spelling_in(directory, name, folder=False):
    """The real spelling of ``name`` in ``directory``: the exact name if present,
    else the one case-insensitive match, else None. (Windows file systems
    match any case, Linux does not, so a reference must use the real one.)
    ``name`` is a file, or with ``folder`` a sub-folder."""
    d = Path(directory)
    if not d.is_dir():
        return None
    names = [p.name for p in d.iterdir() if (p.is_dir() if folder else p.is_file())]
    if name in names:
        return name
    hits = [n for n in names if n.lower() == name.lower()]
    return hits[0] if len(hits) == 1 else None


def real_path_in(root, rel):
    """The real spelling of the file ``rel`` (a '/'-separated path under ``root``),
    resolved one component at a time with :func:`spelling_in`, so a folder in
    the wrong letter case is caught as well as the file name. None when a
    component is not there (or is ambiguous)."""
    cur, out = Path(root), []
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts:
        return None
    for i, part in enumerate(parts):
        if part == "..":
            cur, hit = cur.parent, part
        else:
            hit = spelling_in(cur, part, folder=i < len(parts) - 1)
            if hit is None:
                return None
            cur = cur / hit
        out.append(hit)
    return "/".join(out)


def find_model_in_library(name, library):
    """Library-relative path of <name> (real spelling, folders included) in the
    model folder, else in the extra ``model_search_dirs`` in order; None if in
    none of them."""
    cfg = libcfg.as_config(library)
    for d in cfg.model_search_path:
        hit = real_path_in(cfg.library_root, d + "/" + name)
        if hit:
            return hit
    return None


def footprint_dirs(library, all_libs=False):
    """The footprint libraries to check: the category libraries (every
    ``<footprint_dir>/<library_prefix>*.pretty``, plus the ``.pretty`` of each
    configured category, whatever its name) or, with all_libs, every .pretty
    under the footprint folder."""
    cfg = libcfg.as_config(library)
    base = Path(cfg.library_root) / cfg.footprint_dir
    pat = "*.pretty" if all_libs else glob.escape(cfg.library_prefix) + "*.pretty"
    dirs = set(d for d in base.glob(pat) if d.is_dir())
    if not all_libs:
        dirs |= set(base / c.fp_dir for c in cfg.categories if (base / c.fp_dir).is_dir())
    return sorted(dirs)


def footprint_files(library, all_libs=False):
    """Footprint files of :func:`footprint_dirs`, sorted."""
    return sorted(p for d in footprint_dirs(library, all_libs) for p in d.glob("*.kicad_mod"))


def check_library(library, all_libs=False):
    """Scan footprints; return a report dict with one row per footprint and a
    fix plan (footprints whose refs name a file that is in the model folder)."""
    cfg = libcfg.as_config(library)
    root = Path(cfg.library_root)
    rows, counts = [], {}
    for fp in footprint_files(cfg, all_libs):
        text = read_text(fp)
        refs = model_refs(text)
        rel = fp.relative_to(root).as_posix()
        if not refs:
            counts["none"] = counts.get("none", 0) + 1
            rows.append({"footprint": rel, "ref": None, "kind": "none", "fix": None})
            continue
        # What apply_fixes will do, in the same order: rewrite a dead reference,
        # or remove it when the footprint already names the file it would get.
        named = list(refs)
        for r in refs:
            kind, found = classify_ref(r, cfg)
            counts[kind] = counts.get(kind, 0) + 1
            fix, action = None, None
            if kind in ("case", "bare", "absolute", "other-var") and found:
                fix = cfg.library_mount + "/" + found
                action = "remove" if fix in [x for x in named if x != r] else "rewrite"
                named = [x for x in named if x != r] + ([] if action == "remove" else [fix])
            rows.append({"footprint": rel, "ref": r, "kind": kind, "fix": fix, "fix_action": action})
    problems = [r for r in rows if r["kind"] in PROBLEM_KINDS]
    return {
        "library_root": str(root),
        "footprints": len({r["footprint"] for r in rows}),
        "counts": counts,
        "problems": problems,
        "fixable": [r for r in problems if r["fix"]],
        "unfixable": [r for r in problems if not r["fix"]],
        "rows": rows,
    }


def apply_fixes(library, fixable, dry_run=False):
    """Fix each fixable reference in place: rewrite it, or remove it when the
    footprint already names the same file (see fix_ref). Returns the list of
    footprint files (library-relative) that changed (or would change)."""
    root = Path(libcfg.as_config(library).library_root)
    by_fp = {}
    for r in fixable:
        by_fp.setdefault(r["footprint"], {})[r["ref"]] = r["fix"]
    changed = []
    for rel, mapping in sorted(by_fp.items()):
        p = root / rel
        text = read_text(p)
        new = text
        for old, fix in mapping.items():
            new, _ = fix_ref(new, old, fix)
        if new != text:
            changed.append(rel)
            if not dry_run:
                write_text(p, new)
    return changed


# ---------------------------------------------------------------- KiCad check

def _windows_install_dirs():
    """KiCad 10 and 9 default install folders on Windows (under %ProgramFiles%)."""
    base = os.environ.get("ProgramFiles") or os.path.join(os.environ.get("SystemDrive", "C:") + os.sep,
                                                          "Program Files")
    return [os.path.join(base, "KiCad", v, "bin") for v in ("10.0", "9.0")]


def find_kicad(kicad_bin=None):
    """Return (kicad_cli, kicad_python) or raise RuntimeError.

    ``kicad_bin`` (--kicad-bin) or, failing that, ``$KICAD_BIN`` is
    authoritative: when either is set only that folder is used, and an error
    is raised when it holds no kicad-cli (so ``KICAD_BIN=/nonexistent`` hides
    any installed KiCad). Without them: the KiCad 10 / 9 default install
    folders on Windows, then kicad-cli on PATH. The folder must also hold a
    Python with pcbnew (KiCad's own, as on Windows), or this interpreter must
    import pcbnew."""
    exe = ".exe" if os.name == "nt" else ""
    explicit = [(kicad_bin, "--kicad-bin"), (os.environ.get("KICAD_BIN"), "KICAD_BIN")]
    named = next(((d, what) for d, what in explicit if d), None)
    if named:
        d, what = named
        if not os.path.isfile(os.path.join(d, "kicad-cli" + exe)):
            raise RuntimeError("no kicad-cli in %s %s" % (what, d))
        cands = [d]
    else:
        cands = _windows_install_dirs() if os.name == "nt" else []
        on_path = shutil.which("kicad-cli")
        if on_path:
            cands.append(os.path.dirname(on_path))
    no_python = None
    for d in cands:
        cli = os.path.join(d, "kicad-cli" + exe)
        if not os.path.isfile(cli):
            continue
        py = os.path.join(d, "python" + exe)
        if os.path.isfile(py):
            return cli, py
        try:
            import pcbnew  # noqa: F401
            return cli, sys.executable
        except ImportError:
            no_python = d
    if no_python:
        raise RuntimeError("kicad-cli found in %s, but no Python with pcbnew next to it, and this Python "
                           "cannot import pcbnew: run the tool with KiCad's Python, or point --kicad-bin / "
                           "KICAD_BIN at a folder holding both" % no_python)
    raise RuntimeError("KiCad not found: pass --kicad-bin <KiCad bin folder> or set KICAD_BIN")


def verify_in_kicad(footprint_paths, library_roots, kicad_bin=None, keep_dir=None, timeout=600,
                    library_mount=None):
    """Load each footprint into one throwaway board under KiCad and export STEP;
    return the helper's JSON report (see kicad_lib_verify.py).

    footprint_paths must sit in folders named *.pretty. library_roots are
    searched in order for ``<library_mount>/<rel>`` model files.
    library_mount defaults to the default mount of the last library root."""
    cli, py = find_kicad(kicad_bin)
    if not footprint_paths:  # e.g. a symbol-only zip: nothing to load
        return {"kicad_version": None, "kicad_cli_exit": None, "checked": 0, "loaded": [], "failed": [],
                "no_body": [], "no_model": [], "load_errors": [], "log": []}
    if library_mount is None:
        if not library_roots:
            raise ValueError("library_mount is needed when no library root is given")
        library_mount = libcfg.LibraryConfig(library_roots[-1]).library_mount
    helper = Path(__file__).resolve().parent / "kicad_lib_verify.py"
    work = keep_dir or tempfile.mkdtemp(prefix="kpi_3d_verify_")
    os.makedirs(work, exist_ok=True)
    # The footprint list goes in a file: 100+ absolute paths overflow the
    # Windows command line (WinError 206).
    listing = os.path.join(str(work), "footprints.txt")
    with open(listing, "w", encoding="utf-8") as fh:
        fh.write("\n".join(str(Path(p).resolve()) for p in footprint_paths) + "\n")
    args = [py, "-I", str(helper), "--kicad-cli", cli, "--work", str(work), "--mount", library_mount,
            "--list", listing]
    for r in library_roots:
        args += ["--lib-root", str(Path(r).resolve())]
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("KiCad check could not run: %s" % exc)
    try:
        report = json.loads(r.stdout)
    except ValueError:
        raise RuntimeError("KiCad check failed (exit %d): %s" % (r.returncode, (r.stderr or r.stdout)[-2000:]))
    if keep_dir is None:
        shutil.rmtree(work, ignore_errors=True)
    return report
