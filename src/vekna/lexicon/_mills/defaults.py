import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, JsonValue, ValidationError

from vekna.lexicon._pacts import Config, Ritual, RitualDefinitionError
from vekna.wire import Refusal, refusals


class Default(NamedTuple):
    value: JsonValue
    source: Path


def _flag(field: str) -> str:
    return f"--{field.replace('_', '-')}"


# Said the way the operator typed it: the flag, not the model's field, and the
# ritual rather than a components class they may never have opened.
def _flag_refusal(
    *, ritual: Ritual, refusal: Refusal, given: Mapping[str, JsonValue]
) -> str:
    if not refusal.loc:
        return f"{ritual.name}: {refusal.msg}"
    field = str(refusal.loc[0])
    if refusal.kind == "missing":
        return f"{ritual.name}: {_flag(field)} is required"
    return f"{ritual.name}: {_flag(field)} {given.get(field)!r}: {refusal.msg}"


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
    # operator would watch a ritual ignore a default they believe they set. A
    # value it cannot take would surface at the cast as a flag nobody typed.
    def of(self, ritual: Ritual) -> Mapping[str, Default]:
        found = self._tables.get(ritual.name, {})
        for key, default in found.items():
            if key not in ritual.components.model_fields:
                msg = (
                    f"{default.source}: [defaults.{ritual.name}] sets {key!r},"
                    f" which {ritual.name} does not take"
                )
                raise RitualDefinitionError(msg)
        self._check_values(ritual, found)
        return found

    # Validated as a whole model, with only the config's keys, so a field the
    # config leaves to the flags reads as missing and is not this check's. Any
    # other refusal of a field is of one the config set: its keys are checked
    # against the model's fields above.
    @staticmethod
    def _check_values(ritual: Ritual, found: Mapping[str, Default]) -> None:
        values = {key: default.value for key, default in found.items()}
        try:
            ritual.components.model_validate(values)
        except ValidationError as error:
            for refusal in refusals(error):
                if refusal.kind == "missing" or not refusal.loc:
                    continue
                default = found[str(refusal.loc[0])]
                msg = (
                    f"{default.source}: [defaults.{ritual.name}]"
                    f" {refusal.loc[0]} = {json.dumps(default.value)}: {refusal.msg}"
                )
                raise RitualDefinitionError(msg) from error

    def components(self, ritual: Ritual, given: Mapping[str, JsonValue]) -> BaseModel:
        fields = ritual.components.model_fields
        if unknown := [key for key in given if key not in fields]:
            msg = (
                f"{ritual.name} takes no {', '.join(_flag(key) for key in unknown)}"
                f" (it takes {', '.join(_flag(key) for key in fields) or 'nothing'})"
            )
            raise RitualDefinitionError(msg)
        values = {key: default.value for key, default in self.of(ritual).items()}
        try:
            return ritual.components.model_validate(values | dict(given))
        except ValidationError as error:
            msg = "\n".join(
                _flag_refusal(ritual=ritual, refusal=refusal, given=given)
                for refusal in refusals(error)
            )
            raise RitualDefinitionError(msg) from error
