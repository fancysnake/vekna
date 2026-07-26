import hashlib
import importlib
import importlib.util
import tomllib
from pathlib import Path

from pydantic import ValidationError

from vekna.lexicon._pacts import (
    Config,
    Ritual,
    RitualDefinitionError,
    RitualSource,
    Step,
)


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
    return _found(vars(module))  # type: ignore [misc]


def load_rituals_module(name: str) -> RitualSource:
    return _found(vars(importlib.import_module(name)))  # type: ignore [misc]


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
