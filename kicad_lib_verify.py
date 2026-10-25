"""Check that footprints' 3D models load in KiCad. Run with KiCad's own Python
(it imports pcbnew); kicad_lib_3d.verify_in_kicad() launches it.

usage: python -I kicad_lib_verify.py --kicad-cli PATH --work DIR --mount MOUNT
                                     [--lib-root DIR ...] (--list FILE | FOOTPRINT.kicad_mod ...)

--list FILE names one footprint per line (long lists overflow the Windows
command line).

MOUNT is how projects reach the library root: ``${KIPRJMOD}`` or
``${KIPRJMOD}/<path>`` (the library inside, or next to, the project), or
``${VAR}`` / ``${VAR}/<path>`` for any other path variable.

Each footprint file must sit in a folder named *.pretty. The script

1. loads every footprint with pcbnew.FootprintLoad and places them on a grid
   in one new board, reference V<n>, inside a board outline;
2. lays the work folder out like a project that mounts the library: every
   model path of the form <MOUNT>/<rel> gets <lib-root>/<rel> copied to where
   <MOUNT> points in that throwaway project (first --lib-root that has it
   wins; for a ${VAR} mount, kicad-cli runs with VAR set to a folder in the
   work folder). Other path forms are left as they are, so they fail exactly
   as they would in a real project;
3. saves verify.kicad_pcb and a minimal verify.kicad_pro (kicad-cli needs the
   project file for ${KIPRJMOD}), runs `kicad-cli pcb export step` and reads
   its messages.

kicad-cli exits 0 even when models are missing, so the report comes from its
output: "Could not add 3D model for V3." + the reason on the next line, or
"No model for filename '<path>'." for a file that exists but is not a model.

Prints one JSON object on stdout:
  {"kicad_version", "checked", "loaded": [...], "failed": [{footprint, ref,
   model, reason, body_loaded}], "no_body": [...], "no_model": [...],
   "load_errors": [...], "log": [...]}
"failed" has one row per model that did not load. body_loaded is true when
another (model ...) of the same footprint did load, so the part still has its
3D body and the failing block is a dead extra reference. "no_body" lists the
footprints that carry models but got no body at all.
"""
import argparse
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys

_MOUNT_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}(?:/(.*))?$")


def mount_layout(work, mount):
    """Where the throwaway project and the mounted library go inside ``work``.

    Returns (project_dir, mount_dir, env): the folder that holds the board and
    project file, the folder <MOUNT> resolves to, and the environment
    variables kicad-cli needs. A mount that climbs out of the project
    (``${KIPRJMOD}/../lib``) gets a project folder nested deep enough that
    everything stays inside ``work``."""
    m = _MOUNT_RE.match(mount.replace("\\", "/").rstrip("/"))
    if not m:
        raise ValueError("--mount %r must be ${KIPRJMOD}[/<path>] or ${VAR}[/<path>]" % mount)
    var, sub = m.group(1), posixpath.normpath(m.group(2) or ".")
    parts = [] if sub == "." else sub.split("/")
    ups = 0
    while ups < len(parts) and parts[ups] == "..":
        ups += 1
    base = work if var == "KIPRJMOD" else os.path.join(work, "env_" + var)
    anchor = os.path.join(base, *(["p"] * ups)) if ups else base
    mount_dir = os.path.normpath(os.path.join(anchor, *parts)) if parts else anchor
    if var == "KIPRJMOD":
        return anchor, mount_dir, {}
    return work, mount_dir, {var: anchor}


def main(argv=None):
    import pcbnew

    ap = argparse.ArgumentParser()
    ap.add_argument("--kicad-cli", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--mount", required=True)
    ap.add_argument("--lib-root", action="append", default=[])
    ap.add_argument("--list")
    ap.add_argument("footprints", nargs="*")
    a = ap.parse_args(argv)
    if a.list:
        with open(a.list, encoding="utf-8") as fh:
            a.footprints += [ln.strip() for ln in fh if ln.strip()]
    if not a.footprints:
        ap.error("no footprints given")
    try:
        project, mount_dir, env_extra = mount_layout(os.path.abspath(a.work), a.mount)
    except ValueError as exc:
        ap.error(str(exc))
    mount_prefix = a.mount.replace("\\", "/").rstrip("/") + "/"

    os.makedirs(project, exist_ok=True)
    board = pcbnew.BOARD()
    placed = {}          # ref -> {"footprint": path, "models": [...]}
    load_errors = []
    cols = 8
    pitch = 20.0
    for i, path in enumerate(a.footprints):
        lib_dir, fname = os.path.split(os.path.abspath(path))
        name = fname[:-len(".kicad_mod")] if fname.endswith(".kicad_mod") else fname
        try:
            fp = pcbnew.FootprintLoad(lib_dir, name)
        except Exception as exc:  # KiCad raises IO_ERROR as a Python exception
            fp = None
            load_errors.append({"footprint": path, "error": str(exc)})
        if fp is None:
            if not any(e["footprint"] == path for e in load_errors):
                load_errors.append({"footprint": path, "error": "FootprintLoad returned None"})
            continue
        ref = "V%d" % (i + 1)
        fp.SetReference(ref)
        x, y = 10 + pitch * (i % cols), 10 + pitch * (i // cols)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y)))
        models = [m.m_Filename for m in fp.Models()]
        placed[ref] = {"footprint": path, "models": models}
        for m in models:
            if not m.startswith(mount_prefix):
                continue
            rel = m[len(mount_prefix):]
            for root in a.lib_root:
                src = os.path.join(root, *rel.split("/"))
                if os.path.isfile(src):
                    dst = os.path.join(mount_dir, *rel.split("/"))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                    break
        board.Add(fp)

    rows = max(1, (len(a.footprints) + cols - 1) // cols)
    outline = pcbnew.PCB_SHAPE(board)
    outline.SetShape(pcbnew.SHAPE_T_RECTANGLE)
    outline.SetStart(pcbnew.VECTOR2I(0, 0))
    outline.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20 + pitch * cols), pcbnew.FromMM(20 + pitch * rows)))
    outline.SetLayer(pcbnew.Edge_Cuts)
    board.Add(outline)

    pcb = os.path.join(project, "verify.kicad_pcb")
    pcbnew.SaveBoard(pcb, board)
    with open(os.path.join(project, "verify.kicad_pro"), "w") as fh:
        fh.write('{"meta": {"filename": "verify.kicad_pro", "version": 1}}\n')

    env = dict(os.environ)
    env.update(env_extra)
    r = subprocess.run([a.kicad_cli, "pcb", "export", "step", "-f", "-o",
                        os.path.join(os.path.abspath(a.work), "verify.step"), pcb],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    log = [ln.strip() for ln in (r.stdout + "\n" + r.stderr).splitlines() if ln.strip()]

    failed = []
    bad_refs = set()
    unreadable_seen = set()  # (ref, model file name) already reported as unreadable
    for k, ln in enumerate(log):
        m = re.match(r"Could not add 3D model for (\S+?)\.?$", ln)
        if m and m.group(1) in placed:
            ref = m.group(1)
            reason = log[k + 1] if k + 1 < len(log) else ""
            model = reason.split(":", 1)[1].strip() if reason.startswith("File not found:") else None
            failed.append({"footprint": placed[ref]["footprint"], "ref": ref, "model": model, "reason": reason})
            bad_refs.add(ref)
            continue
        m = re.match(r"No model for filename '(.+)'\.?$", ln)
        if m:
            base = re.split(r"[\\/]", m.group(1))[-1].lower()
            why = log[k - 1] if k > 0 and log[k - 1].startswith("Cannot identify") else ln
            for ref, info in placed.items():
                if (ref, base) in unreadable_seen:  # the line repeats once per footprint using the file
                    continue
                if any(re.split(r"[\\/]", x)[-1].lower() == base for x in info["models"]):
                    failed.append({"footprint": info["footprint"], "ref": ref, "model": m.group(1),
                                   "reason": "not a readable model file: " + why})
                    bad_refs.add(ref)
                    unreadable_seen.add((ref, base))

    # A footprint can carry several (model ...) blocks. kicad-cli reports each one
    # that fails (one "Could not add" line per model), and still exports the
    # others, so a part whose dead extra reference fails still gets its body.
    fail_count = {}
    for f in failed:
        fail_count[f["ref"]] = fail_count.get(f["ref"], 0) + 1
    for f in failed:
        f["body_loaded"] = fail_count[f["ref"]] < len(placed[f["ref"]]["models"])
    loaded = [info["footprint"] for ref, info in placed.items() if info["models"] and ref not in bad_refs]
    no_body = sorted({f["footprint"] for f in failed if not f["body_loaded"]})
    no_model = [info["footprint"] for ref, info in placed.items() if not info["models"]]
    print(json.dumps({
        "kicad_version": pcbnew.Version(),
        "kicad_cli_exit": r.returncode,
        "checked": len(a.footprints),
        "loaded": loaded,
        "failed": failed,
        "no_body": no_body,
        "no_model": no_model,
        "load_errors": load_errors,
        "log": log[-50:],
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
