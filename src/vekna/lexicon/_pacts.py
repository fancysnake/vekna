from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import UnionType


class RitualError(Exception):
    pass


class WorkflowBudgetExceededError(RitualError):
    pass


class RitualDefinitionError(RitualError):
    pass


class StepBoundaryError(RitualError):
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


def goto(target: Step, payload: object = None) -> Goto:
    return Goto(target=target, payload=payload)


def done(result: object = None) -> Done:
    return Done(result=result)
