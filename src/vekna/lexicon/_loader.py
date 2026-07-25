import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

from ._mills import Compendium
from ._pacts import Ritual, RitualDefinitionError, Step

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _register_rituals(
    compendium: Compendium, namespace: dict[str, object], *, source: str
) -> None:
    for value in namespace.values():
        if isinstance(value, Ritual):
            compendium.register(value, source=source)
        elif isinstance(value, Step):
            compendium.register_step(value)


# Derived from the path rather than a fixed "vekna_rituals": two different
# ritual files loaded in one process must not both claim the same module name.
def _module_name(path: Path) -> str:
    return f"vekna_rituals_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"


def load_rituals_file(compendium: Compendium, path: Path) -> None:
    spec = importlib.util.spec_from_file_location(_module_name(path), path)
    if spec is None or spec.loader is None:
        msg = f"cannot import rituals from {path}"
        raise RitualDefinitionError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _register_rituals(compendium, vars(module), source=str(path))


def load_rituals_module(compendium: Compendium, name: str) -> None:
    _register_rituals(
        compendium, vars(importlib.import_module(name)), source=f"module {name}"
    )


def read_config(path: Path) -> tuple[list[str], list[str]]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("rituals", {})
    if not isinstance(section, dict):
        return [], []
    modules = [m for m in section.get("modules", []) if isinstance(m, str)]
    files = [f for f in section.get("files", []) if isinstance(f, str)]
    return modules, files
