import inspect
from collections.abc import Awaitable, Callable, Coroutine
from types import NoneType
from typing import ParamSpec, Protocol, TypeVar, cast, overload

from pydantic import BaseModel

from vekna.lexicon._pacts import (
    MediumBoundaryError,
    Ritual,
    RitualBoundaryError,
    RitualDefinitionError,
    Step,
    StepBoundaryError,
    Transition,
)
from vekna.lexicon._specs import DEFAULT_MAX_STEPS

from ._annotations import (
    _component_flags,
    _components_model,
    _exits,
    _optional_payload,
    _payloads,
)
from .engine import NAMESPACE_SEPARATOR, medium_rite, register_step

_P = ParamSpec("_P")
_MediumT = TypeVar("_MediumT")
_PayloadT = TypeVar("_PayloadT", bound=BaseModel)
_ComponentsT = TypeVar("_ComponentsT", bound=BaseModel)
# The payload of a step `@step(...)` is applied to later, scoped to that call.
_LaterT = TypeVar("_LaterT", bound=BaseModel)


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
# nothing about the return, so the call side names it here. The `| None` is the
# legacy `goto(target)` with no payload — it goes with the shim.
_Called = Callable[[BaseModel | None], Transition | Awaitable[Transition]]

_SUMMARY_WIDTH = 60


# One line, cut to fit, of what the call was actually given. Cut here rather
# than at the surface: `summary` is what the journal keeps, and a 5KB prompt
# under that name is not a summary. Not `textwrap.shorten`, which drops a token
# longer than the width entirely — a no-space command or URL would summarize to
# a bare `…`.
def _cut(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= _SUMMARY_WIDTH:
        return collapsed
    return collapsed[: _SUMMARY_WIDTH - 1] + "…"


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
    head = next(iter(signature.parameters), "")

    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _MediumT:
        # What a rite's line says the call is *doing*: the medium's first
        # argument — a shell's command, an agent's prompt. The declared first
        # parameter, not the first string the caller happened to write:
        # `shell(cwd=..., command=...)` is legal, and kwargs keep call-site
        # order, so scanning would summarize the cwd. Named through `head` so a
        # keyword-only first parameter — `pick(*, prompt, options)` — reads the
        # same as a positional one.
        first = args[0] if args else kwargs.get(head)
        summary = _cut(first) if isinstance(first, str) and first.strip() else None
        # Inside the rite, not before it: the call is what failed, so the rite
        # that names the medium is where the failure belongs.
        async with medium_rite(name, summary=summary):
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


# The one shape both wrappers end on. The question is whether what came back
# still needs awaiting, so that is what gets asked — the alternative, an
# isinstance against `Goto | Done`, answers it by enumerating the transitions
# instead, which is a second copy of that union living in a module whose job is
# not to know what a transition is. `iscoroutinefunction` at decoration time
# would also miss a `def` body that hands back a coroutine, and costs a
# TypeGuard whose typeshed signature is Any-tainted.
async def _settled(outcome: Transition | Awaitable[Transition]) -> Transition:
    return await outcome if isinstance(outcome, Awaitable) else outcome


class _StepDecorator(Protocol):
    def __call__(self, func: _Written[_PayloadT], /) -> Step: ...


# Bare `@step`, or `@step(max_visits=N)` to cap how often one cast re-enters it
# — a recovery loop that never converges ends there rather than on the
# ritual's whole `max_steps`.
@overload
def step(func: _Written[_PayloadT], /) -> Step: ...
@overload
def step(*, max_visits: int) -> _StepDecorator: ...
def step(
    func: _Written[_PayloadT] | None = None, /, *, max_visits: int | None = None
) -> Step | _StepDecorator:
    if func is None:
        if max_visits is not None and max_visits < 1:
            msg = f"@step max_visits must be at least 1, got {max_visits}"
            raise RitualDefinitionError(msg)

        def wrap(written: _Written[_LaterT]) -> Step:
            return _step(written, max_visits=max_visits)

        return wrap
    return _step(func, max_visits=None)


def _step(func: _Written[_PayloadT], *, max_visits: int | None) -> Step:
    name = func.__name__
    erased = cast("_Called", func)
    exits, ends = _exits(erased, decorator="step")
    legacy = exits is None
    payloads = _payloads(erased, legacy=legacy)
    # ponytail: a legacy step annotated `Work | None` is fed by a bare
    # `goto(target)`; on the new path a payload is a model and nothing else.
    accepted: tuple[type, ...] = (
        (*payloads, NoneType) if legacy and _optional_payload(erased) else payloads
    )

    async def run(payload: BaseModel | None) -> Transition:
        # The cast above is discharged here: what the annotation declared is
        # checked against what arrived, and only then is the step called. The
        # engine routes by class and cannot miss; the trial's `walk` can.
        if not isinstance(payload, accepted):
            expected = " | ".join(model.__name__ for model in payloads)
            msg = f"step {name!r} expected {expected}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await _settled(erased(payload))

    the_step = Step(
        name=name,
        run=run,
        payloads=payloads,
        exits=exits,
        ends=ends,
        max_visits=max_visits,
    )
    # A legacy step is reached by `goto`, never by class, and its payload class
    # may be shared — cabinet feeds one `Work` to fifteen steps.
    if not legacy:
        register_step(the_step)
    return the_step


# A structural callback, so `wrap` below cannot declare it as a base. Its point
# is to scope `_ComponentsT` to the decorator `ritual` returns rather than to
# `ritual` itself, where the call site names only the ritual and has nothing to
# bind the variable from.
class _RitualDecorator(Protocol):
    def __call__(self, func: _Written[_ComponentsT]) -> Ritual: ...


def ritual(name: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> _RitualDecorator:
    if NAMESPACE_SEPARATOR in name:
        msg = (
            f"ritual {name!r}: {NAMESPACE_SEPARATOR!r} is reserved for a tome's "
            "namespace"
        )
        raise RitualDefinitionError(msg)

    def wrap(func: _Written[_ComponentsT]) -> Ritual:
        erased = cast("_Called", func)
        model = _components_model(erased)
        exits, ends = _exits(erased, decorator="ritual")

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
            exits=exits,
            ends=ends,
        )

    return wrap


component_flags = _component_flags
