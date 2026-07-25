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
    Step,
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
        self._steps: dict[str, Step] = {}

    def register(self, ritual: Ritual) -> None:
        if ritual.name in self._rituals:
            msg = f"ritual {ritual.name!r} is already registered"
            raise RitualDefinitionError(msg)
        self._rituals[ritual.name] = ritual

    # Steps are collected for `rituals show` only, so a name collision across
    # modules is not worth an error — the first definition wins.
    def register_step(self, the_step: Step) -> None:
        self._steps.setdefault(the_step.name, the_step)

    def step(self, name: str) -> Step | None:
        return self._steps.get(name)

    def ritual(self, name: str) -> Ritual:
        try:
            return self._rituals[name]
        except KeyError:
            msg = f"no ritual named {name!r}"
            raise RitualDefinitionError(msg) from None

    def names(self) -> list[str]:
        return sorted(self._rituals)


# A medium declares that it needs a Focus and how to obtain one; a Focus
# package registers itself. The hint is stated once, at declaration, rather
# than passed to every lookup for an error the lookup may never raise.
class FocusRegistry:
    def __init__(self) -> None:
        self._foci: dict[str, object] = {}
        self._hints: dict[str, str] = {}

    def expect(self, medium_name: str, *, hint: str) -> None:
        self._hints[medium_name] = hint

    def register(self, medium_name: str, focus: object) -> None:
        self._foci[medium_name] = focus

    def resolve(self, medium_name: str) -> object:
        if (focus := self._foci.get(medium_name)) is not None:
            return focus
        msg = f"no Focus registered for medium {medium_name!r}"
        if hint := self._hints.get(medium_name):
            msg = f"{msg} — {hint}"
        raise FocusMissingError(msg)

    def reset(self) -> None:
        self._foci.clear()


_registry = FocusRegistry()


def expect_focus(medium_name: str, *, hint: str) -> None:
    _registry.expect(medium_name, hint=hint)


def register_focus(medium_name: str, focus: object) -> None:
    _registry.register(medium_name, focus)


def resolve_focus(medium_name: str) -> object:
    return _registry.resolve(medium_name)


def reset_foci() -> None:
    _registry.reset()


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
def _current_rite_id(rite: RiteContext) -> str:
    if (rite_id := rite.parent_id) is None:
        msg = "no rite is running — deltas belong to a step or a medium"
        raise RitualError(msg)
    return rite_id


# The one way a medium streams output into its own rite.
def emit_delta(text: str) -> None:
    rite = current_rite()
    rite.grimoire.rite_delta(_current_rite_id(rite), text)


# The one place a rite is opened and closed. A rite whose body raises is
# journaled with status="error" — steps and mediums alike, which is the whole
# reason both call sites share this.
@contextlib.asynccontextmanager
async def _rite(
    *, name: str, category: Literal["step", "medium"]
) -> AsyncIterator[None]:
    parent = current_rite()
    rite_id = parent.grimoire.rite_started(
        name=name, parent_id=parent.parent_id, category=category
    )
    outcome = RiteOutcome()
    token = _current_rite.set(replace(parent, parent_id=rite_id, outcome=outcome))
    finished = False
    try:
        yield
        finished = True
    finally:
        _current_rite.reset(token)
        parent.grimoire.rite_finished(
            rite_id, status="ok" if finished else "error", result=outcome.result
        )


def medium_rite(name: str) -> contextlib.AbstractAsyncContextManager[None]:
    return _rite(name=name, category="medium")


async def run_cast(
    *, ritual: Ritual, components: BaseModel, grimoire: Grimoire, channel: Channel
) -> object:
    token = _current_rite.set(RiteContext(grimoire=grimoire, channel=channel))
    try:
        transition = await ritual.run(components)
        for _ in range(ritual.max_steps):
            if isinstance(transition, Done):
                break
            async with _rite(name=transition.target.name, category="step"):
                transition = await transition.target.run(transition.payload)
    finally:
        _current_rite.reset(token)
    if isinstance(transition, Done):
        return transition.result
    # Leaving the loop still mid-flight means the budget ran out, not that the
    # ritual finished — the only reason the check appears twice.
    msg = f"ritual {ritual.name!r} exceeded max_steps={ritual.max_steps}"
    raise WorkflowBudgetExceededError(msg)
