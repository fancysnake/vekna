from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, JsonValue

from vekna.lexicon._pacts import Config, Ritual, RitualDefinitionError


class Default(NamedTuple):
    value: JsonValue
    source: Path


# Per ritual, per key, with the file that said it. Configs come in precedence
# order, so a project key overrides its global twin and spares the rest.
class Defaults:
    def __init__(self, configs: Iterable[tuple[Path, Config]]) -> None:
        self._tables: dict[str, dict[str, Default]] = {}
        for path, config in configs:
            for name, table in config.defaults.items():
                self._tables.setdefault(name, {}).update(
                    (key, Default(value, path)) for key, value in table.items()
                )

    # A key the ritual does not take would be dropped by its model, and the
    # operator would watch a ritual ignore a default they believe they set.
    def of(self, ritual: Ritual) -> Mapping[str, Default]:
        found = self._tables.get(ritual.name, {})
        for key, default in found.items():
            if key not in ritual.components.model_fields:
                msg = (
                    f"{default.source}: [defaults.{ritual.name}] sets {key!r},"
                    f" which {ritual.name} does not take"
                )
                raise RitualDefinitionError(msg)
        return found

    def components(self, ritual: Ritual, given: Mapping[str, JsonValue]) -> BaseModel:
        values = {key: default.value for key, default in self.of(ritual).items()}
        return ritual.components.model_validate(values | dict(given))
