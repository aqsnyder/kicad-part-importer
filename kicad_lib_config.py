"""Settings for kicad-part-importer: which library to work on, where things live
in it, how the category libraries are named, how footprints reference 3D
models, and what the tool does with git.

Every setting has a generic default. Override them, highest first, with:

1. command-line flags (``--library``, ``--library-prefix``, ``--model-dir``,
   ``--library-mount``, ``--commit`` / ``--no-commit`` ...);
2. environment variables ``KICAD_PART_IMPORTER_<SETTING>`` (the setting name
   in upper case, e.g. ``KICAD_PART_IMPORTER_LIBRARY_PREFIX``);
3. a config file: the one named by ``--config`` or
   ``$KICAD_PART_IMPORTER_CONFIG``, else ``kicad-part-importer.toml`` or
   ``kicad-part-importer.json`` in the library root.

The library root itself comes from ``--library``, then
``$KICAD_PART_IMPORTER_LIBRARY_ROOT``, then ``library_root`` in an explicit
config file, then the nearest folder at or above the current directory that
holds a config file (the way git finds ``.git``), and finally the current
directory.

Standard library only (reading a TOML config needs Python 3.11+ or the
``tomli`` package; JSON always works).
"""

import json
import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

ENV_PREFIX = "KICAD_PART_IMPORTER_"
CONFIG_ENV = ENV_PREFIX + "CONFIG"
CONFIG_FILE_NAMES = ("kicad-part-importer.toml", "kicad-part-importer.json")
DOCS_URL = "https://github.com/aqsnyder/kicad-part-importer/blob/main/docs/configuration.md"

DEFAULT_LIBRARY_PREFIX = "lib_"
DEFAULT_SYMBOL_DIR = "lib_sym"
DEFAULT_FOOTPRINT_DIR = "lib_fp"
DEFAULT_MODEL_DIR = "3d_models"

# (key, description): one symbol library <prefix><key>.kicad_sym and one
# footprint library <prefix><key>.pretty per category, in menu order.
DEFAULT_CATEGORIES = (
    ("connectors", "Connectors, headers, sockets, and interconnects"),
    ("passives", "Resistors, capacitors, inductors, and other passive components"),
    ("semiconductors_discretes", "Diodes, transistors, and other discrete semiconductors"),
    ("ics_general", "General purpose integrated circuits"),
    ("power_management", "Power management ICs, regulators, and converters"),
    ("mcus_soc", "Microcontrollers, SoCs, and processors"),
    ("memory_storage", "Memory devices, storage, and flash"),
    ("rf_communication", "RF components, antennas, and communication modules"),
    ("sensors", "Sensors, transducers, and measurement devices"),
    ("optoelectronics_displays", "LEDs, displays, optocouplers, and optical components"),
    ("electromechanical", "Switches, relays, motors, and electromechanical components"),
    ("protection", "Protection devices, fuses, and ESD protection"),
    ("mechanicals_misc", "Mechanical parts, hardware, and miscellaneous components"),
)

# KiCad's own symbol libraries: --migrate-schematic leaves parts from these alone.
DEFAULT_STOCK_SYMBOL_LIBRARIES = (
    "Device", "power", "Connector", "Connector_Generic", "Switch", "Transistor_FET", "Reference_Voltage",
    "Analog_DAC", "Analog_ADC", "MCU_ST_STM32", "Interface_USB", "Timer", "Regulator_Linear",
    "Regulator_Switching", "Logic", "Memory_Flash",
)

# Every setting, in the order --show-config prints them.
SETTINGS = ("library_root", "library_prefix", "symbol_dir", "footprint_dir", "model_dir", "model_search_dirs",
            "project_dir", "library_mount", "model_prefix", "categories", "stock_symbol_libraries",
            "git_commit", "git_push", "git_message_prefix")
_PATH_SETTINGS = ("library_root", "project_dir")
_LIST_SETTINGS = ("model_search_dirs", "stock_symbol_libraries")
_BOOL_SETTINGS = ("git_commit", "git_push")
# Settings an environment variable can set (lists of tables only come from a file).
ENV_SETTINGS = ("library_root", "library_prefix", "symbol_dir", "footprint_dir", "model_dir",
                "model_search_dirs", "project_dir", "library_mount", "model_prefix",
                "git_commit", "git_push", "git_message_prefix")

_TRUE = ("1", "true", "yes", "on")
_FALSE = ("0", "false", "no", "off", "")

_VAR_PATH_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}(?:/.*)?$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_BAD_NAME_CHARS = set('/\\:"')


class ConfigError(ValueError):
    """A setting is invalid, or a config file cannot be read (exit code 2 on the command line)."""


def _type_name(value):
    return type(value).__name__


def _check_str(value, what):
    if type(value) is not str:
        raise ConfigError("%s must be a string (got %s)" % (what, _type_name(value)))
    return value


def _check_bool(value, what):
    if type(value) is not bool:
        raise ConfigError("%s must be true or false (got %s)" % (what, _type_name(value)))
    return value


def parse_bool(text, what):
    """An environment-variable boolean: 1/true/yes/on or 0/false/no/off (any case)."""
    v = text.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    raise ConfigError("%s=%r: use 1/true/yes/on or 0/false/no/off" % (what, text))


def _name_part(value, what, allow_empty=False):
    """A library name or name prefix: no path separators, colons or quotes."""
    _check_str(value, what)
    if not value and not allow_empty:
        raise ConfigError("%s must not be empty" % what)
    if any(c in _BAD_NAME_CHARS or ord(c) < 32 for c in value):
        raise ConfigError("%s %r: library names cannot hold / \\ : \" or control characters" % (what, value))
    return value


def _rel_dir(value, what):
    """A folder inside the library root, as a POSIX path ('3d_models', 'vendor/models')."""
    _check_str(value, what)
    p = value.replace("\\", "/").strip()
    if not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p):
        raise ConfigError("%s %r must be a folder inside the library root (a relative path)" % (what, value))
    p = posixpath.normpath(p)
    if p == "." or p == ".." or p.startswith("../"):
        raise ConfigError("%s %r must name a folder inside the library root" % (what, value))
    return p


def _mount(value, what="library_mount"):
    _check_str(value, what)
    m = value.replace("\\", "/").strip().rstrip("/")
    if not _VAR_PATH_RE.match(m):
        raise ConfigError("%s %r must start with a KiCad path variable, e.g. ${KIPRJMOD}/my_kicad_library"
                          % (what, value))
    return m


def default_mount(library_root, project_dir):
    """How a project in ``project_dir`` reaches the library: ``${KIPRJMOD}/<path from
    the project folder to the library root>`` (``${KIPRJMOD}`` alone when they are
    the same folder)."""
    root = Path(library_root).resolve()
    try:
        rel = os.path.relpath(str(root), str(Path(project_dir).resolve()))
    except ValueError:  # another drive on Windows
        rel = root.name
    rel = rel.replace(os.sep, "/")
    return "${KIPRJMOD}" if rel == "." else "${KIPRJMOD}/" + rel


class Category:
    """One category: symbol library ``<name>.kicad_sym`` + footprint library ``<name>.pretty``."""

    __slots__ = ("key", "description", "name", "prefix")

    def __init__(self, key, description="", name=None, prefix=DEFAULT_LIBRARY_PREFIX):
        _check_str(key, "category key")
        if not _KEY_RE.match(key):
            raise ConfigError("category key %r: use letters, digits, _ and -, not starting with a digit" % key)
        self.key = key
        self.description = _check_str(description if description is not None else "",
                                      "description of category %r" % key)
        self.prefix = prefix
        self.name = _name_part(name if name is not None else prefix + key, "library name of category %r" % key)

    @property
    def sym_file(self):
        return self.name + ".kicad_sym"

    @property
    def fp_dir(self):
        return self.name + ".pretty"

    @property
    def custom_name(self):
        """True when the library name is not simply <prefix><key>."""
        return self.name != self.prefix + self.key

    def to_dict(self):
        return {"key": self.key, "name": self.name, "description": self.description}


def _categories(spec, prefix):
    if type(spec) not in (list, tuple):
        raise ConfigError("categories must be a list (got %s)" % _type_name(spec))
    out, keys, names = [], set(), set()
    for item in spec:
        if type(item) is Category:
            cat = item
        elif type(item) is str:
            cat = Category(item, "", None, prefix)
        elif type(item) in (list, tuple) and 1 <= len(item) <= 3:
            cat = Category(item[0], item[1] if len(item) > 1 else "", item[2] if len(item) > 2 else None, prefix)
        elif type(item) is dict:
            unknown = sorted(set(item) - {"key", "description", "name"})
            if unknown:
                raise ConfigError("category %r: unknown field(s) %s (known: key, description, name)"
                                  % (item.get("key"), ", ".join(unknown)))
            if "key" not in item:
                raise ConfigError("every category needs a key (got %r)" % (item,))
            cat = Category(item["key"], item.get("description", ""), item.get("name"), prefix)
        else:
            raise ConfigError("a category is a key, or a table with key / description / name (got %r)" % (item,))
        if cat.key in keys:
            raise ConfigError("category key %r is listed twice" % cat.key)
        if cat.name in names:
            raise ConfigError("library name %r is used by two categories" % cat.name)
        keys.add(cat.key)
        names.add(cat.name)
        out.append(cat)
    if not out:
        raise ConfigError("categories must not be empty")
    return out


def _str_list(value, what):
    if type(value) not in (list, tuple):
        raise ConfigError("%s must be a list of strings (got %s)" % (what, _type_name(value)))
    return [_check_str(v, "an entry of " + what) for v in value]


class LibraryConfig:
    """The library layout, naming and git behaviour. Construct it directly
    (unset settings take their defaults) or with :func:`resolve_config`
    (flags, environment, file)."""

    def __init__(self, library_root=None, library_prefix=DEFAULT_LIBRARY_PREFIX, symbol_dir=DEFAULT_SYMBOL_DIR,
                 footprint_dir=DEFAULT_FOOTPRINT_DIR, model_dir=DEFAULT_MODEL_DIR, model_search_dirs=(),
                 project_dir=None, library_mount=None, model_prefix=None, categories=None,
                 stock_symbol_libraries=None, git_commit=False, git_push=False, git_message_prefix="",
                 config_file=None, library_root_source=None):
        self.library_root = Path(library_root) if library_root is not None else Path.cwd()
        self.library_prefix = _name_part(library_prefix, "library_prefix", allow_empty=True)
        self.symbol_dir = _rel_dir(symbol_dir, "symbol_dir")
        self.footprint_dir = _rel_dir(footprint_dir, "footprint_dir")
        self.model_dir = _rel_dir(model_dir, "model_dir")
        self.model_search_dirs = tuple(_rel_dir(d, "model_search_dirs entry")
                                       for d in _str_list(model_search_dirs, "model_search_dirs"))
        self.project_dir = Path(project_dir) if project_dir is not None else self.library_root.resolve().parent
        self.library_mount = (_mount(library_mount) if library_mount is not None
                              else default_mount(self.library_root, self.project_dir))
        if model_prefix is not None:
            _check_str(model_prefix, "model_prefix")
            if not model_prefix.strip():
                raise ConfigError("model_prefix must not be empty")
            self.model_prefix = model_prefix
        else:
            self.model_prefix = self.library_mount + "/" + self.model_dir
        self.categories = _categories(DEFAULT_CATEGORIES if categories is None else categories,
                                      self.library_prefix)
        self.stock_symbol_libraries = tuple(
            DEFAULT_STOCK_SYMBOL_LIBRARIES if stock_symbol_libraries is None
            else _str_list(stock_symbol_libraries, "stock_symbol_libraries"))
        self.git_commit = _check_bool(git_commit, "git_commit")
        self.git_push = _check_bool(git_push, "git_push")
        self.git_message_prefix = _check_str(git_message_prefix, "git_message_prefix")
        self.config_file = Path(config_file) if config_file is not None else None
        self.library_root_source = library_root_source

    @property
    def model_search_path(self):
        """Folders searched, in order, for a model a footprint names by another path."""
        return (self.model_dir,) + tuple(d for d in self.model_search_dirs if d != self.model_dir)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "config_file": str(self.config_file) if self.config_file else None,
            "library_root": str(self.library_root),
            "library_root_source": self.library_root_source,
            "library_prefix": self.library_prefix,
            "symbol_dir": self.symbol_dir,
            "footprint_dir": self.footprint_dir,
            "model_dir": self.model_dir,
            "model_search_dirs": list(self.model_search_dirs),
            "project_dir": str(self.project_dir),
            "library_mount": self.library_mount,
            "model_prefix": self.model_prefix,
            "categories": [c.to_dict() for c in self.categories],
            "stock_symbol_libraries": list(self.stock_symbol_libraries),
            "git_commit": self.git_commit,
            "git_push": self.git_push,
            "git_message_prefix": self.git_message_prefix,
        }


def as_config(library) -> LibraryConfig:
    """A LibraryConfig as is; a path becomes the default configuration for that library root."""
    if hasattr(library, "library_mount"):  # a LibraryConfig (or a subclass)
        return library
    return LibraryConfig(library)


def toml_reader():
    """The TOML parser (``tomllib`` on Python 3.11+, else ``tomli``), or None."""
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads
    except ImportError:
        pass
    try:
        import tomli
        return tomli.loads
    except ImportError:
        return None


def _toml_loads():
    loads = toml_reader()
    if loads is None:
        raise ConfigError("a .toml config needs Python 3.11+ or the tomli package "
                          "(pip install tomli); a .json config works everywhere")
    return loads


def _join(base, path) -> Path:
    """base / path with '..' folded away (an absolute path stays as it is)."""
    return Path(os.path.normpath(str(Path(base) / path)))


def load_config_file(path) -> Dict[str, Any]:
    """Read a TOML or JSON config file. Relative paths in it are relative to its folder."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        raise ConfigError("cannot read config file %s: %s" % (p, exc))
    suffix = p.suffix.lower()
    try:
        if suffix == ".toml":
            data = _toml_loads()(raw.decode("utf-8"))
        elif suffix == ".json":
            data = json.loads(raw.decode("utf-8-sig"))
        else:
            raise ConfigError("config file %s: the name must end in .toml or .json" % p)
    except ConfigError:
        raise
    except Exception as exc:  # tomllib.TOMLDecodeError, ValueError, UnicodeDecodeError
        raise ConfigError("config file %s: %s" % (p, exc))
    if type(data) is not dict:
        raise ConfigError("config file %s: the top level must be a table / object" % p)
    unknown = sorted(set(data) - set(SETTINGS))
    if unknown:
        raise ConfigError("config file %s: unknown setting(s) %s (known: %s)"
                          % (p, ", ".join(unknown), ", ".join(SETTINGS)))
    base = p.resolve().parent
    out = {}
    for key, value in data.items():
        if key in _PATH_SETTINGS:
            out[key] = _join(base, _check_str(value, key))
        elif key in _LIST_SETTINGS:
            out[key] = _str_list(value, key)
        elif key in _BOOL_SETTINGS:
            out[key] = _check_bool(value, key)
        elif key == "categories":
            out[key] = value
        else:
            out[key] = _check_str(value, key)
    return out


def _from_env(environ, cwd) -> Dict[str, Any]:
    out = {}
    for name in ENV_SETTINGS:
        var = ENV_PREFIX + name.upper()
        if var not in environ:
            continue
        value = environ[var]
        if name in _PATH_SETTINGS:
            out[name] = _join(cwd, value)
        elif name == "model_search_dirs":
            out[name] = [v for v in value.split(os.pathsep) if v.strip()]
        elif name in _BOOL_SETTINGS:
            out[name] = parse_bool(value, var)
        else:
            out[name] = value
    return out


def config_files_in(folder) -> List[Path]:
    """The config files (``kicad-part-importer.toml`` / ``.json``) present in ``folder``."""
    return [Path(folder) / n for n in CONFIG_FILE_NAMES if (Path(folder) / n).is_file()]


def find_library_root(start) -> Optional[Path]:
    """The nearest folder at or above ``start`` that holds a config file, or None.

    This is how git finds ``.git``: run the tool anywhere inside a library and it
    works on that library."""
    here = Path(os.path.abspath(str(start)))
    for folder in (here,) + tuple(here.parents):
        if config_files_in(folder):
            return folder
    return None


def resolve_config(cli: Optional[Mapping[str, Any]] = None, environ: Optional[Mapping[str, str]] = None,
                   cwd=None, discover: bool = True) -> LibraryConfig:
    """Merge defaults < config file < environment < command line into a LibraryConfig.

    cli maps setting names to values, None meaning "not given"; the extra key
    ``config`` names a config file. Relative paths on the command line and in
    the environment are relative to ``cwd`` (default: the current directory).

    The library root is, in order: ``cli['library_root']``,
    ``$KICAD_PART_IMPORTER_LIBRARY_ROOT``, ``library_root`` in an explicit
    config file, then (with ``discover`` and no explicit config file) the
    nearest folder at or above ``cwd`` that holds a config file, then ``cwd``.
    The result's ``library_root_source`` says which.
    """
    cli = {k: v for k, v in (cli or {}).items() if v is not None}
    environ = os.environ if environ is None else environ
    cwd = Path(cwd) if cwd is not None else Path.cwd()
    explicit = cli.pop("config", None) or environ.get(CONFIG_ENV) or None
    unknown = sorted(set(cli) - set(SETTINGS))
    if unknown:
        raise ConfigError("unknown setting(s) %s" % ", ".join(unknown))
    for key in _PATH_SETTINGS:
        if key in cli:
            cli[key] = _join(cwd, cli[key])
    env = _from_env(environ, cwd)

    config_file, from_file = None, {}
    if explicit:
        config_file = cwd / explicit
        from_file = load_config_file(config_file)
    if "library_root" in cli:
        root, source = cli["library_root"], "command line"
    elif "library_root" in env:
        root, source = env["library_root"], "environment"
    elif "library_root" in from_file:
        root, source = from_file["library_root"], "config file"
    else:
        found = find_library_root(cwd) if (discover and not explicit) else None
        root, source = (found, "discovered") if found is not None else (cwd, "current directory")
    if not explicit:
        found = config_files_in(root)
        if len(found) > 1:
            raise ConfigError("both %s and %s are in %s; keep one" % (CONFIG_FILE_NAMES + (root,)))
        if found:
            config_file = found[0]
            from_file = load_config_file(config_file)
            if "library_root" in from_file:
                raise ConfigError("%s: library_root is only read from a file given with --config or %s"
                                  % (config_file, CONFIG_ENV))
    merged = dict(from_file)
    merged.update(env)
    merged.update(cli)
    merged["library_root"] = root
    return LibraryConfig(config_file=config_file, library_root_source=source, **merged)


# ------------------------------------------------------------ starter config

def infer_categories(library_root, symbol_dir=DEFAULT_SYMBOL_DIR, footprint_dir=DEFAULT_FOOTPRINT_DIR,
                     library_prefix=DEFAULT_LIBRARY_PREFIX, known=()) -> List[Dict[str, str]]:
    """Categories for an existing library: one per ``<prefix>*.kicad_sym`` in the
    symbol folder or ``<prefix>*.pretty`` in the footprint folder.

    A library that is one of the ``known`` categories (:class:`Category`, e.g.
    the configured or default ones) keeps that category's key, description and
    menu order; the other libraries follow, sorted by name. A library name
    whose remainder is not a valid key keeps its name under a made-up key
    (``acme_74xx`` -> key ``c_74xx``, name ``acme_74xx``)."""
    root = Path(library_root)
    names = set()
    for folder, suffix in ((root / symbol_dir, ".kicad_sym"), (root / footprint_dir, ".pretty")):
        if not folder.is_dir():
            continue
        for p in folder.iterdir():
            if p.name.endswith(suffix) and p.name.startswith(library_prefix):
                if (suffix == ".pretty") == p.is_dir():
                    names.add(p.name[:-len(suffix)])
    out, keys = [], set()
    for cat in known:
        if cat.name in names and cat.key not in keys:
            d = {"key": cat.key}
            if cat.description:
                d["description"] = cat.description
            if cat.name != library_prefix + cat.key:
                d["name"] = cat.name
            out.append(d)
            keys.add(cat.key)
            names.discard(cat.name)
    for name in sorted(names, key=str.lower):
        rest = name[len(library_prefix):]
        if rest and _KEY_RE.match(rest) and rest not in keys:
            out.append({"key": rest})
            keys.add(rest)
            continue
        key = "c_" + (re.sub(r"[^A-Za-z0-9_-]", "_", rest) or "lib")
        base, n = key, 2
        while key in keys:
            key, n = "%s_%d" % (base, n), n + 1
        keys.add(key)
        out.append({"key": key, "name": name})
    return out


def _toml_str(value):
    # A JSON string is a valid TOML basic string (same escapes, \uXXXX included);
    # TOML also wants DEL escaped, which JSON leaves alone.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_list(values, indent="    ", width=100):
    if not values:
        return "[]"
    items = [_toml_str(v) for v in values]
    one_line = "[" + ", ".join(items) + "]"
    if len(one_line) <= width - 30:
        return one_line
    lines, cur = [], indent
    for it in items:
        piece = it + ","
        if len(cur) + len(piece) + 1 > width and cur.strip():
            lines.append(cur.rstrip())
            cur = indent
        cur += piece + " "
    lines.append(cur.rstrip())
    return "[\n" + "\n".join(lines) + "\n]"


def _rel_to(path, base):
    try:
        rel = os.path.relpath(str(Path(path).resolve()), str(Path(base).resolve()))
    except ValueError:  # another drive on Windows: keep it absolute
        return str(Path(path).resolve())
    return rel.replace(os.sep, "/")


def starter_config(cfg: LibraryConfig, explicit=(), fmt="toml", version=None) -> str:
    """The text of a config file that pins ``cfg`` (all but ``library_root``) for
    its library root, as written by ``--init``.

    ``library_mount`` is always written, so the library keeps its mount
    whatever its checkout folder is called. ``model_prefix`` and
    ``project_dir`` are written only when named in ``explicit`` (they follow
    the other settings otherwise)."""
    root = Path(cfg.library_root)
    cats = []
    for c in cfg.categories:
        d = {"key": c.key}
        if c.description:
            d["description"] = c.description
        if c.custom_name:
            d["name"] = c.name
        cats.append(d)
    project_rel = _rel_to(cfg.project_dir, root)

    if fmt == "json":
        data = {
            "library_prefix": cfg.library_prefix,
            "symbol_dir": cfg.symbol_dir,
            "footprint_dir": cfg.footprint_dir,
            "model_dir": cfg.model_dir,
            "model_search_dirs": list(cfg.model_search_dirs),
            "library_mount": cfg.library_mount,
        }
        if "model_prefix" in explicit:
            data["model_prefix"] = cfg.model_prefix
        if "project_dir" in explicit:
            data["project_dir"] = project_rel
        data.update({
            "git_commit": cfg.git_commit,
            "git_push": cfg.git_push,
            "git_message_prefix": cfg.git_message_prefix,
            "stock_symbol_libraries": list(cfg.stock_symbol_libraries),
            "categories": cats,
        })
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if fmt != "toml":
        raise ValueError("fmt must be 'toml' or 'json'")

    def commented(key, value):
        return ("%s = %s" if key in explicit else "# %s = %s") % (key, value)

    by = "kicad-part-importer --init" + (" %s" % version if version else "")
    out = [
        "# kicad-part-importer settings for this library (written by %s)." % by,
        "#",
        "# The tool finds this file by walking up from the current directory, so",
        "# any command run in this folder or below it works on this library.",
        "# Paths are relative to this file. Every setting is described in",
        "# " + DOCS_URL,
        "",
        "# Category libraries are named <library_prefix><key>:",
        "# <symbol_dir>/<name>.kicad_sym and <footprint_dir>/<name>.pretty.",
        "library_prefix = %s" % _toml_str(cfg.library_prefix),
        "",
        "# Folders inside the library root.",
        "symbol_dir = %s" % _toml_str(cfg.symbol_dir),
        "footprint_dir = %s" % _toml_str(cfg.footprint_dir),
        "model_dir = %s" % _toml_str(cfg.model_dir),
        "",
        "# More folders (inside the library root) where --check-3d --fix-3d looks",
        "# for a model after model_dir, e.g. an old vendor export.",
        "model_search_dirs = %s" % _toml_list(cfg.model_search_dirs),
        "",
        "# How a project reaches this library in footprint model paths: a KiCad",
        "# path variable, optionally followed by a path. ${KIPRJMOD}/<folder> for a",
        "# library inside each project (a git submodule), ${MY_LIB} for a shared one.",
        "library_mount = %s" % _toml_str(cfg.library_mount),
        "",
        "# The model path --link-3d writes. Default: <library_mount>/<model_dir>.",
        commented("model_prefix", _toml_str(cfg.model_prefix)),
        "",
        "# Where --add-to-project finds the project's sym-lib-table and fp-lib-table.",
        "# Default: the folder that holds this library.",
        commented("project_dir", _toml_str(project_rel)),
        "",
        "# Git. git_commit = true commits the library files every command writes",
        "# (as if --commit were given); git_push = true runs git push afterwards",
        "# (as if --push). --no-commit / --no-push override them for one run.",
        "# --dry-run and --check-3d never commit or push, project files (the",
        "# tables --add-to-project edits) are never committed, and --init commits",
        "# or pushes only with --commit / --push on its command line.",
        "git_commit = %s" % ("true" if cfg.git_commit else "false"),
        "git_push = %s" % ("true" if cfg.git_push else "false"),
        "# Put in front of every commit message the tool writes, e.g. \"parts: \".",
        "git_message_prefix = %s" % _toml_str(cfg.git_message_prefix),
        "",
        "# KiCad's own symbol libraries, which --migrate-schematic leaves alone.",
        "stock_symbol_libraries = %s" % _toml_list(cfg.stock_symbol_libraries),
        "",
        "# The categories, in menu order. Each needs a key (letters, digits, _ and -,",
        "# not starting with a digit); description is optional; name (the library",
        "# name) defaults to <library_prefix><key>.",
    ]
    for d in cats:
        out.append("")
        out.append("[[categories]]")
        for k in ("key", "name", "description"):
            if k in d:
                out.append("%s = %s" % (k, _toml_str(d[k])))
    return "\n".join(out) + "\n"


def write_starter_config(cfg: LibraryConfig, explicit=(), fmt=None, version=None) -> Tuple[Path, str]:
    """Write :func:`starter_config` into the library root. ``fmt`` None picks
    TOML when a TOML reader is available (so the file can be read back), else
    JSON. Refuses (ConfigError) when the library root already has a config
    file. Returns (path, format)."""
    root = Path(cfg.library_root)
    existing = config_files_in(root)
    if existing:
        raise ConfigError("%s already exists; edit it instead" % existing[0])
    if fmt is None:
        fmt = "toml" if toml_reader() is not None else "json"
    path = root / ("kicad-part-importer." + fmt)
    root.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(starter_config(cfg, explicit=explicit, fmt=fmt, version=version))
    return path, fmt
