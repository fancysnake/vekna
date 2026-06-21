from collections.abc import Callable
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from vekna.wire import RiteFinished, RiteStarted, WireMessage

from ._pacts import Done, Ritual, RitualDefinitionError, WorkflowBudgetExceededError


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Grimoire:
    def __init__(self, *, cast_id: str, clock: Callable[[], datetime] = _now) -> None:
        self._cast_id = cast_id
        self._clock = clock
        self._events: list[WireMessage] = []
        self._counter = 0

    def rite_started(self, *, name: str, parent_id: str | None = None) -> str:
        self._counter += 1
        rite_id = f"r{self._counter}"
        self._events.append(
            RiteStarted(
                cast_id=self._cast_id,
                rite_id=rite_id,
                parent_id=parent_id,
                name=name,
                category="step",
                started_at=self._clock(),
            )
        )
        return rite_id

    def rite_finished(
        self, rite_id: str, *, status: Literal["ok", "error"] = "ok"
    ) -> None:
        self._events.append(
            RiteFinished(
                cast_id=self._cast_id,
                rite_id=rite_id,
                status=status,
                finished_at=self._clock(),
            )
        )

    @property
    def events(self) -> list[WireMessage]:
        return list(self._events)


class Compendium:
    def __init__(self) -> None:
        self._rituals: dict[str, Ritual] = {}

    def register(self, ritual: Ritual) -> None:
        if ritual.name in self._rituals:
            msg = f"ritual {ritual.name!r} is already registered"
            raise RitualDefinitionError(msg)
        self._rituals[ritual.name] = ritual

    def ritual(self, name: str) -> Ritual:
        try:
            return self._rituals[name]
        except KeyError:
            msg = f"no ritual named {name!r}"
            raise RitualDefinitionError(msg) from None

    def names(self) -> list[str]:
        return sorted(self._rituals)


async def run_cast(
    *, ritual: Ritual, components: BaseModel, grimoire: Grimoire
) -> object:
    transition = await ritual.run(components)
    for _ in range(ritual.max_steps):
        if isinstance(transition, Done):
            return transition.result
        rite_id = grimoire.rite_started(name=transition.target.name)
        transition = await transition.target.run(transition.payload)
        grimoire.rite_finished(rite_id)
    if isinstance(transition, Done):
        return transition.result
    msg = f"ritual {ritual.name!r} exceeded max_steps={ritual.max_steps}"
    raise WorkflowBudgetExceededError(msg)
