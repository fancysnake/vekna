import hashlib
import importlib
import importlib.util
import pkgutil
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

from pydantic import ValidationError

from vekna.lexicon._pacts import (
    Config,
    Ritual,
    RitualDefinitionError,
    RitualSource,
    Step,
)


# The one place a module's namespace is read. Binding it to a declared
# `dict[str, object]` is what discharges the `Any` a module's `__dict__` carries,
# so no load route needs an ignore of its own.
def _found(*, source: str, module: ModuleType) -> RitualSource:
    namespace: dict[str, object] = vars(module)
    return RitualSource(
        source=source,
        rituals=[v for v in namespace.values() if isinstance(v, Ritual)],
        steps=[v for v in namespace.values() if isinstance(v, Step)],
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


# Imported one at a time rather than through `pkgutil.walk_packages`, which
# swallows a submodule's ImportError unless handed an `onerror`: a ritual
# package that does not import must fail the cast as loudly as a rituals.py that
# does not.
def _submodules(*, directory: Path, prefix: str) -> Iterator[tuple[str, ModuleType]]:
    for info in pkgutil.iter_modules([str(directory)]):
        name = f"{prefix}.{info.name}"
        module = importlib.import_module(name)
        yield name, module
        if (nested := _package_directory(module)) is not None:
            yield from _submodules(directory=nested, prefix=name)


# Every module, not just the package's own namespace: `__init__.py` stays empty,
# so a step it does not re-export would otherwise be invisible to the compendium
# — and an unregistered step is drawn as a leaf, which truncates the graph
# `rituals show` prints without saying so.
def _swept(*, name: str, module: ModuleType) -> list[RitualSource]:
    found = [_found(source=name, module=module)]
    if (directory := _package_directory(module)) is None:
        return found
    found += [
        _found(source=sub_name, module=sub)
        for sub_name, sub in _submodules(directory=directory, prefix=name)
    ]
    return found


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
    spec.loader.exec_module(module)
    return [_found(source=str(path), module=module)]


# A real import under the package's real name, not `spec_from_file_location`:
# that route names the module after the path it came from, and the first
# relative import inside it fails on a name no package has.
def load_rituals_package(path: Path) -> list[RitualSource]:
    _on_path(path.parent)
    return _swept(name=path.name, module=importlib.import_module(path.name))


def load_rituals_module(name: str) -> list[RitualSource]:
    return _swept(name=name, module=importlib.import_module(name))


# A config that does not parse stops the command: loading no rituals from it
# would surface later as "no ritual named ...", which names neither the file
# nor the mistake.
def read_config(path: Path) -> Config:
    with path.open("rb") as handle:
        data = tomllib.load(handle)  # type: ignore [misc]

    try:
        return Config.model_validate(data)  # type: ignore [misc]
    except ValidationError as error:
        msg = f"{path}: {error}"
        raise RitualDefinitionError(msg) from error
