from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import UnionType

from pydantic import BaseModel


class RitualError(Exception):
    pass


class WorkflowBudgetExceededError(RitualError):
    pass


class RitualDefinitionError(RitualError):
    pass


class StepBoundaryError(RitualError):
    pass


class StandalonePromptError(RitualError):
    pass


@dataclass(frozen=True)
class Done:
    result: object = None


@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[object], Awaitable["Transition"]]
    input_type: type[object] | UnionType


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


def goto(target: Step, payload: object = None) -> Goto:
    return Goto(target=target, payload=payload)


def done(result: object = None) -> Done:
    return Done(result=result)
