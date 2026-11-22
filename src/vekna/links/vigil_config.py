import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, PositiveInt
from typing_extensions import override

from vekna.pacts.circle import Vigil, VigilBook
from vekna.wire import project_checkouts, read_layers

_log = logging.getLogger(__name__)
_TABLE = "vigil"


class _Vigil(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every: PositiveInt
    ritual: str
    args: dict[str, JsonValue] = {}


# Only `[vigil]` is read here; every other table is somebody else's.
class _File(BaseModel):
    vigil: dict[str, _Vigil] = {}


# The vigils of every project the user's config names with a checkout that is
# there. A project nobody listed is one the daemon has never heard of, so its
# own `.vekna.toml` is not read.
class ConfigVigils(VigilBook):
    def __init__(self) -> None:
        # The daemon asks every few seconds: a problem is logged when it
        # appears, not on every look.
        self._said: frozenset[str] = frozenset()

    @override
    def vigils(self) -> list[Vigil]:
        found: list[Vigil] = []
        problems: list[str] = []
        for checkout in project_checkouts().values():
            if checkout.is_dir():
                read = read_layers(directory=checkout, table=_TABLE, model=_File)
                problems += read.problems
                found += _settled(checkout, read.found)
        for problem in sorted(frozenset(problems) - self._said):
            _log.warning("%s", problem)
        self._said = frozenset(problems)
        return found


# A nearer table replaces a farther one of the same name whole: half of one
# vigil's schedule under another's ritual is a vigil nobody wrote.
def _settled(checkout: Path, layers: list[_File]) -> list[Vigil]:
    named: dict[str, _Vigil] = {}
    for layer in reversed(layers):
        named |= layer.vigil
    return [
        Vigil(
            name=name,
            project_root=str(checkout),
            ritual=vigil.ritual,
            every=vigil.every,
            args=vigil.args,
        )
        for name, vigil in named.items()
    ]


def vigil_problems(directory: Path) -> list[str]:
    return read_layers(directory=directory, table=_TABLE, model=_File).problems
