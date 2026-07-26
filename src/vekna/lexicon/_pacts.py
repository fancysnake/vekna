from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from types import UnionType
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue


class Channel(Protocol):
    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str: ...


GateFn = Callable[[str], Awaitable[bool]]

# The agent's own question, mid-rite: free text when no options are offered.
AskFn = Callable[[str, Sequence[str] | None], Awaitable[str]]


@dataclass(frozen=True)
class CodingCall:
    prompt: str
    model: str | None
    system: str | None
    cwd: str | None
    output_schema: dict[str, JsonValue] | None
    focus_options: object | None


# Typed and closed, not a loose telemetry dict: a focus that spelled a key
# differently used to lose the field silently on the way into CodingResult.
class FocusReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None


class CodingFocusProtocol(Protocol):
    async def run(
        self,
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply: ...


class RitualError(Exception):
    pass


class StepBudgetExceededError(RitualError):
    pass


class RitualDefinitionError(RitualError):
    pass


class StepBoundaryError(RitualError):
    pass


class StandalonePromptError(RitualError):
    pass


class FocusMissingError(RitualError):
    pass


@dataclass(frozen=True)
class Done:
    result: object = None


# `source` is the decorated function's own source text, captured at definition
# time so `rituals show` can read the step graph off it. None when the function
# was built dynamically and has no source to read.
@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[object], Awaitable["Transition"]]
    input_type: type[object] | UnionType
    source: str | None = None


@dataclass(frozen=True)
class Goto:
    target: Step
    payload: object = None


Transition = Goto | Done


@dataclass(frozen=True)
class Ritual:
    name: str
    components: type[BaseModel]
    run: Callable[[BaseModel], Awaitable[Transition]]
    max_steps: int
    source: str | None = None


def goto(target: Step, payload: object = None) -> Goto:
    return Goto(target=target, payload=payload)


def done(result: object = None) -> Done:
    return Done(result=result)
