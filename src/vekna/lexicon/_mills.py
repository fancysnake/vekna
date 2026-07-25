import contextlib
from collections.abc import AsyncIterator, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, JsonValue

from vekna.wire import RiteDelta, RiteFinished, RiteStarted, WireMessage

from ._pacts import (
    Channel,
    Done,
    FocusMissingError,
    Ritual,
    RitualDefinitionError,
    RitualError,
    WorkflowBudgetExceededError,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Grimoire:
    def __init__(
        self,
        *,
        cast_id: str,
        clock: Callable[[], datetime] = _now,
        on_event: Callable[[WireMessage], None] | None = None,
    ) -> None:
        self._cast_id = cast_id
        self._clock = clock
        self._on_event = on_event
        self._events: list[WireMessage] = []
        self._counter = 0

    def _append(self, event: WireMessage) -> None:
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def rite_started(
        self,
        *,
        name: str,
        parent_id: str | None = None,
        category: Literal["step", "medium"] = "step",
    ) -> str:
        self._counter += 1
        rite_id = f"r{self._counter}"
        self._append(
            RiteStarted(
                cast_id=self._cast_id,
                rite_id=rite_id,
                parent_id=parent_id,
                name=name,
                category=category,
                started_at=self._clock(),
            )
        )
        return rite_id

    def rite_delta(self, rite_id: str, delta: str) -> None:
        self._append(RiteDelta(cast_id=self._cast_id, rite_id=rite_id, delta=delta))

    def rite_finished(
        self,
        rite_id: str,
        *,
        status: Literal["ok", "error"] = "ok",
        result: JsonValue | None = None,
    ) -> None:
        self._append(
            RiteFinished(
                cast_id=self._cast_id,
                rite_id=rite_id,
                status=status,
                result=result,
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


_foci: dict[str, object] = {}


def register_focus(medium_name: str, focus: object) -> None:
    _foci[medium_name] = focus


def resolve_focus(medium_name: str, *, hint: str) -> object:
    try:
        return _foci[medium_name]
    except KeyError:
        msg = f"no Focus registered for medium {medium_name!r} — {hint}"
        raise FocusMissingError(msg) from None


@dataclass
class RiteOutcome:
    result: JsonValue | None = None


@dataclass(frozen=True)
class RiteContext:
    grimoire: Grimoire
    channel: Channel
    parent_id: str | None = None
    outcome: RiteOutcome = field(default_factory=RiteOutcome)


def record_result(value: JsonValue) -> None:
    current_rite().outcome.result = value


_current_rite: ContextVar[RiteContext | None] = ContextVar(
    "vekna_current_rite", default=None
)


def current_rite() -> RiteContext:
    if (rite := _current_rite.get()) is None:
        msg = "mediums can only be called inside a running cast"
        raise RitualError(msg)
    return rite


# Deltas need a rite to hang off. Steps and mediums both open one; a ritual
# body runs at the cast root, where there is none.
def current_rite_id() -> str:
    if (rite_id := current_rite().parent_id) is None:
        msg = "no rite is running — deltas belong to a step or a medium"
        raise RitualError(msg)
    return rite_id


@contextlib.asynccontextmanager
async def medium_rite(name: str) -> AsyncIterator[None]:
    parent = current_rite()
    rite_id = parent.grimoire.rite_started(
        name=name, parent_id=parent.parent_id, category="medium"
    )
    outcome = RiteOutcome()
    token = _current_rite.set(replace(parent, parent_id=rite_id, outcome=outcome))
    try:
        yield
    finally:
        _current_rite.reset(token)
        parent.grimoire.rite_finished(rite_id, result=outcome.result)


async def run_cast(
    *, ritual: Ritual, components: BaseModel, grimoire: Grimoire, channel: Channel
) -> object:
    root = RiteContext(grimoire=grimoire, channel=channel)
    token = _current_rite.set(root)
    try:
        transition = await ritual.run(components)
        for _ in range(ritual.max_steps):
            if isinstance(transition, Done):
                return transition.result
            rite_id = grimoire.rite_started(name=transition.target.name)
            step_token = _current_rite.set(replace(root, parent_id=rite_id))
            try:
                transition = await transition.target.run(transition.payload)
            finally:
                _current_rite.reset(step_token)
            grimoire.rite_finished(rite_id)
    finally:
        _current_rite.reset(token)
    if isinstance(transition, Done):
        return transition.result
    msg = f"ritual {ritual.name!r} exceeded max_steps={ritual.max_steps}"
    raise WorkflowBudgetExceededError(msg)
