import inspect
import textwrap
from collections.abc import Awaitable, Callable
from types import NoneType, UnionType
from typing import ParamSpec, TypeGuard, TypeVar, get_args, get_type_hints

from pydantic import BaseModel

from vekna.lexicon._pacts import (
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


def _sole_annotation(
    func: Callable[[BaseModel], Awaitable[Transition]], *, decorator: str, noun: str
) -> object:
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


# Signature-forwarding via ParamSpec is Any-tainted the same way the rest of
# this module is, so `medium` stays here rather than next to `medium_rite` in
# the engine — _mills keeps its strictness.
def medium(
    func: Callable[_P, Awaitable[_MediumT]],
) -> Callable[_P, Awaitable[_MediumT]]:
    name = func.__name__

    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _MediumT:
        async with medium_rite(name):
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
def _payload_type(
    func: Callable[[BaseModel], Awaitable[Transition]],
) -> type[BaseModel] | UnionType:
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


def source_text(func: Callable[[BaseModel], Awaitable[Transition]]) -> str | None:
    try:
        return textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None


def step(func: Callable[[BaseModel], Awaitable[Transition]]) -> Step:
    name = func.__name__
    payload_type = _payload_type(func)

    async def run(payload: BaseModel | None) -> Transition:
        if not isinstance(payload, payload_type):
            msg = f"step {name!r} expected {payload_type}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await func(payload)

    return Step(name=name, run=run, input_type=payload_type, source=source_text(func))


def _components_model(
    func: Callable[[BaseModel], Awaitable[Transition]],
) -> type[BaseModel]:
    annotation = _sole_annotation(func, decorator="ritual", noun="components")
    if (model := _as_model(annotation)) is not None:
        return model
    msg = f"@ritual {func.__name__!r} needs a pydantic model as its components type"
    raise RitualDefinitionError(msg)


def component_flags(components: type[BaseModel]) -> list[tuple[str, str, bool]]:
    flags: list[tuple[str, str, bool]] = []
    for name, field in components.model_fields.items():
        type_name = field.annotation.__name__ if field.annotation else "value"  # type: ignore [misc]
        flags.append((name, type_name, field.is_required()))
    return flags


def ritual(
    name: str, *, max_steps: int = DEFAULT_MAX_STEPS
) -> Callable[[Callable[[BaseModel], Awaitable[Transition]]], Ritual]:
    def wrap(func: Callable[[BaseModel], Awaitable[Transition]]) -> Ritual:
        model = _components_model(func)

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
            return await func(values)

        return Ritual(
            name=name,
            components=model,
            run=run,
            max_steps=max_steps,
            source=source_text(func),
        )

    return wrap
