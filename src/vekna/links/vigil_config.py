import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from typing_extensions import override

from vekna.pacts.circle import Vigil, VigilBook
from vekna.wire import ProblemLog, project_checkouts, read_layers

_log = logging.getLogger(__name__)
_TABLE = "vigil"
# A longer interval carries the due time past what a datetime holds.
_LONGEST_EVERY = 366 * 24 * 3600


class _Vigil(BaseModel):
    model_config = ConfigDict(extra="forbid")

    every: int = Field(gt=0, le=_LONGEST_EVERY)
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
        self._problems = ProblemLog(_log)

    @override
    def vigils(self) -> list[Vigil]:
        found: list[Vigil] = []
        problems: list[str] = []
        for checkout in project_checkouts(problems).values():
            if checkout.is_dir():
                read = read_layers(directory=checkout, table=_TABLE, model=_File)
                problems += read.problems
                found += _settled(checkout, read.found)
        self._problems.warn(problems)
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
