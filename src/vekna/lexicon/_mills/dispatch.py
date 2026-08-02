import inspect
import textwrap
from collections.abc import Awaitable, Callable
from types import NoneType, UnionType
from typing import (
    Annotated,
    ParamSpec,
    TypeGuard,
    TypeVar,
    cast,
    get_args,
    get_type_hints,
)

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

from .engine import medium_rite

_P = ParamSpec("_P")
_MediumT = TypeVar("_MediumT")

# A step declares the payload it takes — `async def measure(state: Uncovered)` —
# and a parameter type is contravariant, so a decorator asking for
# `Callable[[BaseModel], ...]` refuses every step an author will ever write.
# The variable is what lets the declaration through; the erasure below is what
# the runtime works in.
_PayloadT = TypeVar("_PayloadT", bound=BaseModel)


# What the decorators hand their helpers, and what a Step runs: past the
# boundary check the payload is a BaseModel and nothing more, because the type
# it was checked against is a runtime value read off an annotation.
_Erased = Callable[[BaseModel], Awaitable[Transition]]


def _sole_annotation(func: _Erased, *, decorator: str, noun: str) -> object:
    parameters = list(inspect.signature(func).parameters.values())
    if len(parameters) != 1:
        msg = f"@{decorator} {func.__name__!r} must take exactly one {noun} parameter"
        raise RitualDefinitionError(msg)
    return get_type_hints(func).get(parameters[0].name)  # type: ignore [misc]


# The one place a runtime annotation is narrowed, so the reflection boundary's
# exemptions stay at two lines rather than spreading through every caller.
def _as_model(annotation: object) -> type[BaseModel] | None:
    if not isinstance(annotation, type):  # type: ignore [misc]
        return None
    if issubclass(annotation, BaseModel):  # type: ignore [misc]
        return annotation
    return None


def _is_model_union(annotation: object) -> TypeGuard[UnionType]:
    if not isinstance(annotation, UnionType):
        return False
    members: tuple[object, ...] = get_args(annotation)
    return all(
        _as_model(member) is not None or member is NoneType for member in members
    )


# The same check Python is about to perform on the call itself, run early so the
# failure can be named. A keyword a medium no longer takes is a mistake an
# author's rituals.py makes and nothing type-checks — `coding(gate_tools=[...])`
# after `gate_tools` moved into `CodingOpts` — and Python's TypeError reports it
# as a traceback out of the engine's own frames. The unknown keywords are named
# from the signature rather than read off the TypeError, whose wording is the
# interpreter's to change; anything else `bind` refuses is quoted as it came.
def _check_call(
    *,
    name: str,
    signature: inspect.Signature,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> None:
    try:
        signature.bind(*args, **kwargs)
    except TypeError as error:
        if unknown := [key for key in kwargs if key not in signature.parameters]:
            named = ", ".join(repr(key) for key in unknown)
            msg = f"medium {name!r} takes no argument {named}"
        else:
            msg = f"medium {name!r} was called wrong: {error}"
        raise MediumBoundaryError(msg) from error


# Signature-forwarding via ParamSpec is Any-tainted the same way the rest of
# this module is, so `medium` stays here rather than next to `medium_rite` in
# the engine — _mills keeps its strictness.
def medium(
    func: Callable[_P, Awaitable[_MediumT]],
) -> Callable[_P, Awaitable[_MediumT]]:
    name = func.__name__
    # Once, at decoration time: a signature rebuilt per call would put a
    # reflection cost on every medium a cast reaches.
    signature = inspect.signature(func)

    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _MediumT:
        # Inside the rite, not before it: the call is what failed, so the rite
        # that names the medium is where the failure belongs.
        async with medium_rite(name):
            _check_call(name=name, signature=signature, args=args, kwargs=kwargs)
            return await func(*args, **kwargs)

    # Set directly rather than via functools.wraps, whose _Wrapped return type
    # is Any-tainted: a decorated medium should introspect as itself, not as
    # `wrapped`.
    wrapped.__name__ = name
    wrapped.__qualname__ = getattr(func, "__qualname__", name)
    wrapped.__module__ = getattr(func, "__module__", wrapped.__module__)
    wrapped.__doc__ = func.__doc__
    return wrapped


# A step may admit more than one payload shape — `Lint | Coverage` for a step
# two others transition into — so a union is legal here where a ritual's
# components, being one CLI interface, are not.
def _payload_type(func: _Erased) -> type[BaseModel] | UnionType:
    annotation = _sole_annotation(func, decorator="step", noun="payload")
    if (model := _as_model(annotation)) is not None:
        return model
    if _is_model_union(annotation):
        return annotation
    msg = (
        f"@step {func.__name__!r} needs a pydantic model, or a union of them, "
        "as its payload type"
    )
    raise RitualDefinitionError(msg)


def source_text(func: _Erased) -> str | None:
    try:
        return textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None


def step(func: Callable[[_PayloadT], Awaitable[Transition]]) -> Step:
    name = func.__name__
    erased = cast("_Erased", func)
    payload_type = _payload_type(erased)

    async def run(payload: BaseModel | None) -> Transition:
        # The cast above is discharged here: what the annotation declared is
        # checked against what arrived, and only then is the step called.
        if not isinstance(payload, payload_type):
            msg = f"step {name!r} expected {payload_type}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await erased(payload)

    return Step(name=name, run=run, input_type=payload_type, source=source_text(erased))


def _components_model(func: _Erased) -> type[BaseModel]:
    annotation = _sole_annotation(func, decorator="ritual", noun="components")
    if (model := _as_model(annotation)) is not None:
        return model
    msg = f"@ritual {func.__name__!r} needs a pydantic model as its components type"
    raise RitualDefinitionError(msg)


_NAMELESS = "value"


# Naming an annotation means reading an attribute off whatever the author wrote.
# `name: object` is what keeps that untyped read from spreading: everything below
# narrows by isinstance, as the rest of this module does.
def _plain_name(annotation: object) -> str:
    name: object = getattr(annotation, "__name__", None)
    return name if isinstance(name, str) else _NAMELESS


# 3.14 merged `typing.Union` into `types.UnionType`. Before it, `|` yields the
# typing union whenever a member is an Annotated alias — so `File | None` is a
# `UnionType` on 3.14 but a `_UnionGenericAlias` on 3.11, where an isinstance
# check misses it and the flag rendered `<Optional>`. What both spellings share
# is `__origin__`, and the sentinel is taken from an example rather than named:
# the name is the very thing 3.14 merged away and the linters ask you to drop.
_UNION_ORIGIN: object = getattr(Annotated[int, "example"] | None, "__origin__", None)


def _is_union(annotation: object) -> bool:
    if isinstance(annotation, UnionType):
        return True
    origin: object = getattr(annotation, "__origin__", None)
    return origin is not None and origin is _UNION_ORIGIN


# Two wrappers hide the name a flag should print, and both arrive by way of an
# optional component. A union has no `__name__` worth printing — `str | None`
# rendered `<Union>` on 3.14 and raised AttributeError on 3.11, and
# `File | None` called itself `<Optional>`. And pydantic unwraps a bare
# `Annotated[Path, ...]` into metadata, but inside a union it does not, so
# `File | None` rendered `<Annotated>`. An optional `--only` takes a Path;
# saying so is the whole point of printing a type at all.
def _type_name(annotation: object) -> str:
    if _is_union(annotation):
        members: tuple[object, ...] = get_args(annotation)
        named = [_type_name(member) for member in members if member is not NoneType]
        return "|".join(named) or _NAMELESS
    # `__metadata__` is what makes an alias Annotated; its first arg is the type
    # underneath.
    if hasattr(annotation, "__metadata__"):
        wrapped: tuple[object, ...] = get_args(annotation)
        return _type_name(wrapped[0])
    return _plain_name(annotation)


def component_flags(components: type[BaseModel]) -> list[tuple[str, str, bool]]:
    return [
        (name, _type_name(field.annotation), field.is_required())  # type: ignore [misc]
        for name, field in components.model_fields.items()
    ]


def ritual(
    name: str, *, max_steps: int = DEFAULT_MAX_STEPS
) -> Callable[[Callable[[_PayloadT], Awaitable[Transition]]], Ritual]:
    def wrap(func: Callable[[_PayloadT], Awaitable[Transition]]) -> Ritual:
        erased = cast("_Erased", func)
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
            return await erased(values)

        return Ritual(
            name=name,
            components=model,
            run=run,
            max_steps=max_steps,
            source=source_text(erased),
        )

    return wrap
