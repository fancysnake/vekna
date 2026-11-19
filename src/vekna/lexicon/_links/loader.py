import contextlib
import difflib
import hashlib
import importlib
import importlib.util
import pkgutil
import sys
from collections.abc import Generator, Iterator
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

from pydantic import ValidationError

from vekna.lexicon._pacts import Config, Ritual, RitualDefinitionError, RitualSource
from vekna.wire import (
    ConfigLayer,
    TomlValue,
    config_layers,
    default_config_path,
    explained,
    merged_table,
    read_toml,
)


# The one place a module's namespace is read. Binding it to a declared
# `dict[str, object]` is what discharges the `Any` a module's `__dict__` carries,
# so no load route needs an ignore of its own.
def _found(*, origin: str, module: ModuleType) -> RitualSource:
    namespace: dict[str, object] = vars(module)
    return RitualSource(
        origin=origin, rituals=[v for v in namespace.values() if isinstance(v, Ritual)]
    )


# Derived from the path rather than a fixed "vekna_rituals": two different
# ritual files loaded in one process must not both claim the same module name.
def _module_name(path: Path) -> str:
    return f"vekna_rituals_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"


# A package is a module whose file is its directory's `__init__`. Read off
# `__file__` rather than `__path__`, which a `ModuleType` does not declare and
# which would arrive as `Any`.
def _package_directory(module: ModuleType) -> Path | None:
    if (file := module.__file__) is None or Path(file).stem != "__init__":
        return None
    return Path(file).parent


# What a ritual source raises on import is the author's own error, and the
# traceback is theirs to read — but the message that reaches the terminal has to
# say which file produced it. `No module named 'reqeusts'` names the typo and
# not the place, and a package sweep can be twenty files deep by then.
@contextlib.contextmanager
def _blamed(origin: str) -> Generator[None]:
    try:
        yield
    # A module-level argparse exits on import; that is a source that does not
    # import, not a request to end the command.
    except (Exception, SystemExit) as error:
        msg = f"{origin} failed to import: {error.__class__.__name__}: {error}"
        raise RitualDefinitionError(msg) from error


# Every module, not just the package's own namespace: `__init__.py` stays empty,
# so a ritual it does not re-export would otherwise be invisible to the
# compendium. The root is the first thing yielded rather than a case of its own.
# Imported one at a time rather than through `pkgutil.walk_packages`, which
# swallows a submodule's ImportError unless handed an `onerror`: a ritual
# package that does not import must fail the cast as loudly as a rituals.py that
# does not.
def _modules(*, name: str, module: ModuleType) -> Iterator[tuple[str, ModuleType]]:
    yield name, module
    if (directory := _package_directory(module)) is None:
        return
    for info in pkgutil.iter_modules([str(directory)]):
        sub = f"{name}.{info.name}"
        with _blamed(sub):
            imported = importlib.import_module(sub)
        yield from _modules(name=sub, module=imported)


# So that a ritual package can be imported by its own name, which is what
# relative imports inside it resolve against. `vekna` is a console script, so
# sys.path[0] is the venv's bin and the project root is on nothing's path.
def _on_path(directory: Path) -> None:
    if (entry := str(directory)) not in sys.path:
        sys.path.insert(0, entry)


# A list of one, so that every route hands `_inits` the same shape: a package
# yields one entry per module swept.
def load_rituals_file(path: Path) -> list[RitualSource]:
    spec = importlib.util.spec_from_file_location(_module_name(path), path)
    if spec is None or spec.loader is None:
        msg = f"cannot import rituals from {path}"
        raise RitualDefinitionError(msg)
    module = importlib.util.module_from_spec(spec)
    with _blamed(str(path)):
        spec.loader.exec_module(module)
    return [_found(origin=str(path), module=module)]


# A real import under the package's real name, not `spec_from_file_location`:
# that route names the module after the path it came from, and the first
# relative import inside it fails on a name no package has.
def load_rituals_package(path: Path) -> list[RitualSource]:
    _on_path(path.parent)
    with _blamed(str(path)):
        module = importlib.import_module(path.name)
    # `import_module` answers from `sys.modules` before it consults `sys.path`,
    # so a package of this name already loaded — an installed distribution, a
    # test that imported one earlier — would hand back its rituals under the
    # discovered path's name. Silently casting someone else's rituals is worse
    # than not casting at all.
    if _package_directory(module) != path:
        msg = f"{path.name!r} was already imported from somewhere other than {path}"
        raise RitualDefinitionError(msg)
    return [
        _found(origin=name, module=found)
        for name, found in _modules(name=path.name, module=module)
    ]


# `root` is the cwd, which is what `PYTHONPATH=.` used to have to say: a
# configured `modules = ["myproj.rituals"]` names a package in the project being
# cast, and nothing puts that project on the path of a console script.
def load_rituals_module(name: str, *, root: Path) -> list[RitualSource]:
    _on_path(root)
    with _blamed(name):
        module = importlib.import_module(name)
    return [
        _found(origin=found_name, module=found)
        for found_name, found in _modules(name=name, module=module)
    ]


# Dispatching on the shape of a path is the loader's business: `_inits` binds
# what it gets to the compendium, and a caller that had to ask `is_dir()` first
# would be routing around the dedup that lives on the one entry point.
def load_rituals_source(path: Path) -> list[RitualSource]:
    return load_rituals_package(path) if path.is_dir() else load_rituals_file(path)


# Not a closed set: other tools keep their tables in the same file. `[circle]`
# is the daemon's, read in its own process.
_TABLES = (*Config.model_fields, "circle", "window")


# A table vekna does not read is somebody else's, unless it is a near spelling
# of one vekna does: a `[ritual]` would otherwise load nothing and leave the
# next cast to fail with "no ritual named ...".
def _misspelt(layer: ConfigLayer) -> None:
    for table in layer.tables:
        if table in _TABLES:
            continue
        if meant := difflib.get_close_matches(table, _TABLES, n=1, cutoff=0.8):
            msg = (
                f"{layer.source}: vekna reads no [{table}] table"
                f" — did you mean [{meant[0]}]?"
            )
            raise RitualDefinitionError(msg)


def _layers(directory: Path) -> list[ConfigLayer]:
    layers, problems = config_layers(directory)
    if problems:
        raise RitualDefinitionError("\n".join(problems))
    return layers


# A config that does not parse stops the command: loading no rituals from it
# would surface later as "no ritual named ...", which names neither the file
# nor the mistake.
# The user's table for a project names tomes only. A ritual the project defines
# lives in its tree, and a path from here would name the checkout where a cast
# in a pooled worktree must read its own tree.
def read_config(layer: ConfigLayer) -> Config:
    _misspelt(layer)
    try:
        config = Config.model_validate(layer.tables)
    except ValidationError as error:
        msg = f"{layer.source}: {explained(error)}"
        raise RitualDefinitionError(msg) from error
    if layer.project is not None and config.rituals.files:
        msg = (
            f"{layer.table('rituals')} takes no files"
            " — rituals a project defines are named in its own .vekna.toml"
        )
        raise RitualDefinitionError(msg)
    return config


# Every config that speaks for `cwd`, nearest first.
def read_configs(cwd: Path) -> list[tuple[ConfigLayer, Config]]:
    return [(layer, read_config(layer)) for layer in _layers(cwd)]


# What the user's file says for a checkout that is gone.
# A table `config_layers` refuses is its to name, and is passed over here.
def idle_projects() -> list[str]:
    user = default_config_path()
    try:
        projects = read_toml(user).get("projects")
    except (OSError, ValueError):
        return []
    idle: list[str] = []
    for name, table in projects.items() if isinstance(projects, dict) else ():
        if not isinstance(table, dict) or not isinstance(table.get("path"), str):
            continue
        if not Path(str(table["path"])).expanduser().exists():
            idle.append(
                f"{user}: [projects.{name}] path = {table['path']!r} does not exist"
            )
    return idle


# A tome's own table, as every layer that speaks for `directory` sets it: the
# project's `.vekna.toml` over the user's table for the project over what the
# user says for every project, key by key. `sources` names each table that
# contributed, nearest first, for the error a tome raises over a value.
class ConfigTable(NamedTuple):
    values: dict[str, TomlValue]
    sources: tuple[str, ...]


def config_table(name: str, directory: Path | None = None) -> ConfigTable:
    layers = _layers(Path.cwd() if directory is None else directory)
    said = [layer for layer in layers if name in layer.tables]
    return ConfigTable(
        merged_table(said, name), tuple(layer.table(name) for layer in said)
    )
