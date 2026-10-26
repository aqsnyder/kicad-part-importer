"""Which symbol libraries are KiCad's own (stock), so --migrate-schematic leaves
the parts that use them alone.

A library is stock when

1. ``stock_symbol_libraries`` in the config names it; or
2. the project's sym-lib-table lists it with a path into KiCad's symbol
   folder (``${KICADn_SYMBOL_DIR}/...`` for any n, or a path inside an
   installed symbols folder). The project table decides: a project library
   called ``Device`` that points at the project's own file is not stock; or
3. the project table does not list it, and KiCad's global sym-lib-table
   (nested ``(type "Table")`` tables included, as KiCad 10 writes it) points
   it into KiCad's symbol folder, or an installed symbols folder holds
   ``<name>.kicad_sym`` (or a ``<name>.kicad_symdir`` folder).

KiCad's symbols folders are the ones the ``KICADn_SYMBOL_DIR`` path variables
name (environment, then KiCad's kicad_common.json) when any of them exists,
else the default install folders and the one next to kicad-cli on PATH. The
global table is ``<config>/<version>/sym-lib-table``, where <config> is
``$KICAD_CONFIG_HOME`` or the platform's KiCad settings folder; every version
is read, newest first.

Standard library only.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional

_STOCK_URI_RE = re.compile(r"^\$\{KICAD\d*_SYMBOL_DIR\}")
_SYMBOL_DIR_VAR_RE = re.compile(r"^KICAD(\d*)_SYMBOL_DIR$")
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_LIB_RE = re.compile(r'\(lib\s+\(name\s+"([^"]+)"\)\s*\(type\s+"([^"]+)"\)\s*\(uri\s+"([^"]+)"\)')
_FLATPAK = ".var/app/org.kicad.KiCad"


def _env(environ, name):
    """``environ[name]``, matching the name in any case (Windows variable names are)."""
    if name in environ:
        return environ[name]
    upper = name.upper()
    return next((v for k, v in environ.items() if k.upper() == upper), None)


def _versions_in(folder) -> List[Path]:
    """The ``<major>.<minor>`` subfolders of ``folder``, newest first."""
    try:
        subs = [p for p in Path(folder).iterdir() if _VERSION_RE.match(p.name) and p.is_dir()]
    except OSError:
        return []
    return sorted(subs, key=lambda p: tuple(int(n) for n in p.name.split(".")), reverse=True)


def config_dirs(environ: Optional[Mapping[str, str]] = None) -> List[Path]:
    """KiCad's settings folders, ``<config>/<version>``, newest version first."""
    env = os.environ if environ is None else environ
    home = _env(env, "KICAD_CONFIG_HOME")
    if home:
        bases = [Path(home)]
    elif os.name == "nt":
        appdata = _env(env, "APPDATA")
        bases = [Path(appdata) / "kicad"] if appdata else []
    elif sys.platform == "darwin":
        bases = [Path.home() / "Library" / "Preferences" / "kicad"]
    else:
        xdg = _env(env, "XDG_CONFIG_HOME") or str(Path.home() / ".config")
        bases = [Path(xdg) / "kicad", Path.home() / _FLATPAK / "config" / "kicad"]
    return [d for base in bases for d in _versions_in(base)]


def path_variables(environ: Optional[Mapping[str, str]] = None,
                   configs: Optional[Iterable[Path]] = None) -> Dict[str, str]:
    """KiCad's path variables: the ones set in its preferences (kicad_common.json
    of the newest version that has one), overridden by the environment, as in
    KiCad."""
    env = os.environ if environ is None else environ
    out = {}
    for d in (config_dirs(env) if configs is None else configs):
        try:
            data = json.loads((Path(d) / "kicad_common.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        variables = (data.get("environment") or {}).get("vars") if isinstance(data, dict) else None
        if isinstance(variables, dict):
            out.update((k, v) for k, v in variables.items() if isinstance(k, str) and isinstance(v, str))
        break
    out.update(env)
    return out


def _default_symbol_dirs(environ) -> List[Path]:
    """Where KiCad installs its symbol libraries by default, and next to kicad-cli on PATH."""
    if os.name == "nt":
        base = _env(environ, "ProgramFiles") or os.path.join((_env(environ, "SystemDrive") or "C:") + os.sep,
                                                              "Program Files")
        out = [v / "share" / "kicad" / "symbols" for v in _versions_in(Path(base) / "KiCad")]
    elif sys.platform == "darwin":
        out = [Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")]
    else:
        flatpak = "app/org.kicad.KiCad/current/active/files/share/kicad/symbols"
        out = [Path("/usr/share/kicad/symbols"), Path("/usr/local/share/kicad/symbols"),
               Path("/var/lib/flatpak") / flatpak, Path.home() / ".local/share/flatpak" / flatpak]
    cli = shutil.which("kicad-cli", path=_env(environ, "PATH"))
    if cli:
        bin_dir = Path(cli).resolve().parent
        out += [bin_dir.parent / "share" / "kicad" / "symbols",  # Windows, Linux
                bin_dir.parent / "SharedSupport" / "symbols"]    # macOS (Contents/MacOS/kicad-cli)
    return out


def symbol_dirs(environ: Optional[Mapping[str, str]] = None,
                variables: Optional[Mapping[str, str]] = None) -> List[Path]:
    """KiCad's installed symbols folders: the ones the ``KICADn_SYMBOL_DIR``
    variables name (newest n first) when any of them exists, else the default
    install folders that exist."""
    env = os.environ if environ is None else environ
    variables = path_variables(env) if variables is None else variables
    named = []
    for name, value in variables.items():
        m = _SYMBOL_DIR_VAR_RE.match(name.upper())
        if m and value.strip():
            named.append((int(m.group(1) or 0), Path(value)))
    for cands in ([p for _, p in sorted(named, key=lambda nv: -nv[0])], _default_symbol_dirs(env)):
        out = []
        for c in cands:
            if c.is_dir() and c not in out:
                out.append(c)
        if out:
            return out
    return []


def expand(uri: str, variables: Mapping[str, str]) -> Optional[str]:
    """``uri`` with its ``${VAR}`` references replaced, or None when one is not set."""
    missing = []

    def sub(m):
        value = variables.get(m.group(1))
        if value is None:
            missing.append(m.group(1))
            return m.group(0)
        return value

    out = _VAR_RE.sub(sub, uri)
    return None if missing else out


def read_lib_table(path, variables: Mapping[str, str], _seen=None) -> Dict[str, str]:
    """{name: uri} for every library a sym-lib-table lists, with the libraries of
    the tables it nests (``(type "Table")``) in their place. The first entry of
    a name wins. A table that cannot be read gives nothing."""
    seen = set() if _seen is None else _seen
    key = os.path.normcase(os.path.abspath(str(path)))
    if key in seen:
        return {}
    seen.add(key)
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out = {}
    for name, lib_type, uri in _LIB_RE.findall(text):
        if lib_type.lower() == "table":
            nested = expand(uri, variables)
            if nested is not None:
                for n, u in read_lib_table(Path(path).parent / nested, variables, seen).items():
                    out.setdefault(n, u)
        else:
            out.setdefault(name, uri)
    return out


def global_lib_table(configs: Iterable[Path], variables: Mapping[str, str]) -> Dict[str, str]:
    """KiCad's global sym-lib-table as {name: uri}, every version's, newest first."""
    out = {}
    for d in configs:
        for name, uri in read_lib_table(Path(d) / "sym-lib-table", variables).items():
            out.setdefault(name, uri)
    return out


def _inside(path, folder) -> bool:
    p = os.path.normcase(os.path.abspath(str(path)))
    f = os.path.normcase(os.path.abspath(str(folder))).rstrip("\\/")
    return p.startswith(f + os.sep)


class StockSymbolLibraries:
    """Decides which symbol libraries are stock (see the module docstring).

    ``names`` are the configured ``stock_symbol_libraries``; ``global_table``
    is KiCad's global sym-lib-table ({name: uri}); ``symbol_dirs`` are
    KiCad's installed symbols folders. :meth:`detect` finds the last two."""

    def __init__(self, names: Iterable[str] = (), global_table: Optional[Mapping[str, str]] = None,
                 symbol_dirs: Iterable = (), variables: Optional[Mapping[str, str]] = None):
        self.names = frozenset(names)
        self.global_table = dict(global_table or {})
        self.symbol_dirs = [Path(d) for d in symbol_dirs]
        self.variables = dict(variables or {})
        self._installed = None

    @classmethod
    def detect(cls, names: Iterable[str] = (), environ: Optional[Mapping[str, str]] = None):
        """The configured names plus what this computer's KiCad says."""
        env = os.environ if environ is None else environ
        configs = config_dirs(env)
        variables = path_variables(env, configs)
        return cls(names, global_lib_table(configs, variables), symbol_dirs(env, variables), variables)

    @property
    def installed(self) -> FrozenSet[str]:
        """The library names in KiCad's symbols folders."""
        if self._installed is None:
            found = set()
            for d in self.symbol_dirs:
                try:
                    entries = list(os.scandir(str(d)))
                except OSError:
                    continue
                for e in entries:
                    if e.name.endswith(".kicad_sym") and e.is_file():
                        found.add(e.name[:-len(".kicad_sym")])
                    elif e.name.endswith(".kicad_symdir") and e.is_dir():
                        found.add(e.name[:-len(".kicad_symdir")])
            self._installed = frozenset(found)
        return self._installed

    def is_stock_uri(self, uri: str) -> bool:
        """True for a library path into KiCad's symbol folder."""
        if _STOCK_URI_RE.match(uri):
            return True
        path = expand(uri, self.variables)
        if path is None or not os.path.isabs(path):
            return False
        return any(_inside(path, d) for d in self.symbol_dirs)

    def is_stock(self, name: str, project_table: Optional[Mapping[str, str]] = None) -> bool:
        """True when ``name`` is a stock library for a project whose sym-lib-table
        is ``project_table`` ({name: uri})."""
        if name in self.names:
            return True
        if project_table and name in project_table:
            return self.is_stock_uri(project_table[name])
        if name in self.global_table and self.is_stock_uri(self.global_table[name]):
            return True
        return name in self.installed
