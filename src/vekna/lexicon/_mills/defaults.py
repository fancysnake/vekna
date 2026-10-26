import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

from pydantic import BaseModel, JsonValue, ValidationError

from vekna.lexicon._pacts import Config, Ritual, RitualDefinitionError
from vekna.wire import Refusal, flag_of, refusals


class Default(NamedTuple):
    value: JsonValue
    source: Path


# Said where the value was set: a flag as the operator typed it, a default with
# the file that set it, and the ritual rather than a components class they may
# never have opened.
def _said(
    *,
    ritual: Ritual,
    refusal: Refusal,
    found: Mapping[str, Default],
    given: Mapping[str, JsonValue],
) -> str:
    if not refusal.loc:
        # A dict for its keys: each file once, in the order the configs came.
        sources = {
            str(default.source): None
            for key, default in found.items()
            if key not in given
        }
        if not sources:
            return f"{ritual.name}: {refusal.msg}"
        return (
            f"{ritual.name}: {refusal.msg}"
            f" (with [defaults.{ritual.name}] from {', '.join(sources)})"
        )
    key, *inner = (str(part) for part in refusal.loc)
    msg = f"{'.'.join(inner)}: {refusal.msg}" if inner else refusal.msg
    if key in given:
        return f"{ritual.name}: {flag_of(key)} {given[key]!r}: {msg}"
    if (default := found.get(key)) is not None:
        return (
            f"{default.source}: [defaults.{ritual.name}]"
            f" {key} = {json.dumps(default.value)}: {msg}"
        )
    if refusal.kind == "missing":
        return f"{ritual.name}: {flag_of(key)} is required"
    return f"{ritual.name}: {flag_of(key)}: {msg}"


def _refused(
    *,
    ritual: Ritual,
    said: Iterable[Refusal],
    found: Mapping[str, Default],
    given: Mapping[str, JsonValue],
) -> RitualDefinitionError:
    return RitualDefinitionError(
        "\n".join(
            _said(ritual=ritual, refusal=refusal, found=found, given=given)
            for refusal in said
        )
    )


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
    def _found(self, ritual: Ritual) -> Mapping[str, Default]:
        found = self._tables.get(ritual.name, {})
        for key, default in found.items():
            if key not in ritual.components.model_fields:
                msg = (
                    f"{default.source}: [defaults.{ritual.name}] sets {key!r},"
                    f" which {ritual.name} does not take"
                )
                raise RitualDefinitionError(msg)
        return found

    # Validated as a whole model, with only the config's keys, so a value it
    # cannot take is refused here rather than at every cast. A field the config
    # leaves to the flags reads as missing, and is not this check's.
    def of(self, ritual: Ritual) -> Mapping[str, Default]:
        found = self._found(ritual)
        values = {key: default.value for key, default in found.items()}
        try:
            ritual.components.model_validate(values)
        except ValidationError as error:
            if kept := [
                refusal
                for refusal in refusals(error)
                if refusal.kind != "missing" or len(refusal.loc) > 1
            ]:
                raise _refused(
                    ritual=ritual, said=kept, found=found, given={}
                ) from error
        return found

    def components(self, ritual: Ritual, given: Mapping[str, JsonValue]) -> BaseModel:
        fields = ritual.components.model_fields
        if unknown := [key for key in given if key not in fields]:
            msg = (
                f"{ritual.name} takes no {', '.join(flag_of(key) for key in unknown)}"
                f" (it takes {', '.join(flag_of(key) for key in fields) or 'nothing'})"
            )
            raise RitualDefinitionError(msg)
        found = self._found(ritual)
        values = {key: default.value for key, default in found.items()}
        try:
            return ritual.components.model_validate(values | dict(given))
        except ValidationError as error:
            raise _refused(
                ritual=ritual, said=refusals(error), found=found, given=given
            ) from error
