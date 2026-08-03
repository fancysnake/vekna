import inspect
import textwrap
from collections.abc import Awaitable, Callable, Coroutine
from typing import ParamSpec, Protocol, TypeVar, cast

from pydantic import BaseModel

from vekna.lexicon._pacts import (
    MediumBoundaryError,
    Ritual,
    RitualBoundaryError,
    Step,
    StepBoundaryError,
    Transition,
)
from vekna.lexicon._specs import DEFAULT_MAX_STEPS

from ._annotations import _component_flags, _components_model, _Erased, _payload_type
from .engine import medium_rite

_P = ParamSpec("_P")
_MediumT = TypeVar("_MediumT")
_PayloadT = TypeVar("_PayloadT", bound=BaseModel)
_ComponentsT = TypeVar("_ComponentsT", bound=BaseModel)


# What the author wrote, before the payload type is erased. Their own model as
# the parameter, because a step declared `(fetched: Fetched)` is not a
# `Callable[[BaseModel], ...]` — parameters are contravariant, and typing it as
# one is an error on every decorator in a rituals file the author type-checks.
# And `def` or `async def` as the body needs: routing on a payload has nothing
# to await, and saying `async` to satisfy a signature is a lie the linter is
# right to call.
_Written = Callable[[_PayloadT], Transition | Awaitable[Transition]]

# The same contract with the payload type erased, which is the shape the
# wrappers actually call. `_Erased` next door is the reflection half and says
# nothing about the return, so the call side names it here.
_Called = Callable[[BaseModel], Transition | Awaitable[Transition]]


# Signature-forwarding via ParamSpec is str-tainted the same way the rest of
# this module is, so `medium` stays here rather than next to `medium_rite` in
# the engine — _mills keeps its strictness. It returns a Coroutine rather than
# an Awaitable because `asyncio.create_task` takes the narrower of the two, and
# running two mediums at once is a thing rituals do — `merge_ready.gates` puts
# both gates in a TaskGroup. An Awaitable return made that call untypeable, and
# the `Task[str]` it inferred then spread through everything read off the
# result. `str` for the send and yield types rather than `str`, which this
# project disallows and which nothing here needs.
def medium(
    func: Callable[_P, Awaitable[_MediumT]],
) -> Callable[_P, Coroutine[str, str, _MediumT]]:
    name = func.__name__
    # Once, at decoration time: a signature rebuilt per call would put a
    # reflection cost on every medium a cast reaches.
    signature = inspect.signature(func)

    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _MediumT:
        # Inside the rite, not before it: the call is what failed, so the rite
        # that names the medium is where the failure belongs.
        async with medium_rite(name):
            try:
                signature.bind(*args, **kwargs)
            except TypeError as error:
                if unknown := [
                    key for key in kwargs if key not in signature.parameters
                ]:
                    named = ", ".join(repr(key) for key in unknown)
                    msg = f"medium {name!r} takes no argument {named}"
                else:
                    msg = f"medium {name!r} was called wrong: {error}"
                raise MediumBoundaryError(msg) from error
            return await func(*args, **kwargs)

    # Set directly rather than via functools.wraps, whose _Wrapped return type
    # is str-tainted: a decorated medium should introspect as itself, not as
    # `wrapped`.
    wrapped.__name__ = name
    wrapped.__qualname__ = getattr(func, "__qualname__", name)
    wrapped.__module__ = getattr(func, "__module__", wrapped.__module__)
    wrapped.__doc__ = func.__doc__
    return wrapped


def source_text(func: _Erased) -> str | None:
    try:
        return textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None


# The one shape both wrappers end on. The question is whether what came back
# still needs awaiting, so that is what gets asked — the alternative, an
# isinstance against `Goto | Done`, answers it by enumerating the transitions
# instead, which is a second copy of that union living in a module whose job is
# not to know what a transition is. `iscoroutinefunction` at decoration time
# would also miss a `def` body that hands back a coroutine, and costs a
# TypeGuard whose typeshed signature is Any-tainted.
async def _settled(outcome: Transition | Awaitable[Transition]) -> Transition:
    return await outcome if isinstance(outcome, Awaitable) else outcome


def step(func: _Written[_PayloadT]) -> Step:
    name = func.__name__
    erased = cast("_Called", func)
    payload_type = _payload_type(erased)

    async def run(payload: BaseModel | None) -> Transition:
        # The cast above is discharged here: what the annotation declared is
        # checked against what arrived, and only then is the step called.
        if not isinstance(payload, payload_type):
            msg = f"step {name!r} expected {payload_type}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await _settled(erased(payload))

    return Step(name=name, run=run, input_type=payload_type, source=source_text(erased))


# A structural callback, so `wrap` below cannot declare it as a base. Its point
# is to scope `_ComponentsT` to the decorator `ritual` returns rather than to
# `ritual` itself, where the call site names only the ritual and has nothing to
# bind the variable from.
class _RitualDecorator(Protocol):
    def __call__(self, func: _Written[_ComponentsT]) -> Ritual: ...


def ritual(name: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> _RitualDecorator:
    def wrap(func: _Written[_ComponentsT]) -> Ritual:
        erased = cast("_Called", func)
        model = _components_model(erased)

        # The cast's entry boundary, and the counterpart to the step's: nothing
        # ties the instance the CLI validated to the model this ritual
        # declared, so the check is what makes a mis-wiring say so.
        async def run(values: BaseModel) -> Transition:
            if not isinstance(values, model):
                msg = (
                    f"ritual {name!r} expected {model.__name__}, "
                    f"got {type(values).__name__}"
                )
                raise RitualBoundaryError(msg)
            return await _settled(erased(values))

        return Ritual(
            name=name,
            components=model,
            run=run,
            max_steps=max_steps,
            source=source_text(erased),
        )

    return wrap


component_flags = _component_flags
