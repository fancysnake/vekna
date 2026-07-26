import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path

from vekna.lexicon._pacts import Ritual, RitualDefinitionError, RitualSource, Step

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


def _found(namespace: dict[str, object]) -> RitualSource:
    return RitualSource(
        rituals=[v for v in namespace.values() if isinstance(v, Ritual)],
        steps=[v for v in namespace.values() if isinstance(v, Step)],
    )


# Derived from the path rather than a fixed "vekna_rituals": two different
# ritual files loaded in one process must not both claim the same module name.
def _module_name(path: Path) -> str:
    return f"vekna_rituals_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"


def load_rituals_file(path: Path) -> RitualSource:
    spec = importlib.util.spec_from_file_location(_module_name(path), path)
    if spec is None or spec.loader is None:
        msg = f"cannot import rituals from {path}"
        raise RitualDefinitionError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return _found(vars(module))


def load_rituals_module(name: str) -> RitualSource:
    return _found(vars(importlib.import_module(name)))


def read_config(path: Path) -> tuple[list[str], list[str]]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("rituals", {})
    if not isinstance(section, dict):
        return [], []
    modules = [m for m in section.get("modules", []) if isinstance(m, str)]
    files = [f for f in section.get("files", []) if isinstance(f, str)]
    return modules, files
