import inspect
import textwrap
from collections.abc import Awaitable, Callable
from types import UnionType
from typing import ParamSpec, TypeVar, get_type_hints

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


# Signature-forwarding via ParamSpec is Any-tainted the same way the rest of
# this module is, so `medium` stays here rather than next to `medium_rite` in
# the engine — _mills keeps its strictness.
def medium(
    func: Callable[_P, Awaitable[_MediumT]],
) -> Callable[_P, Awaitable[_MediumT]]:
    name = getattr(func, "__name__", "medium")

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


def _payload_type(
    func: Callable[..., Awaitable[Transition]],
) -> type[object] | UnionType:
    name = getattr(func, "__name__", "<step>")
    parameters = list(inspect.signature(func).parameters.values())
    if len(parameters) != 1:
        msg = f"@step {name!r} must take exactly one payload parameter"
        raise RitualDefinitionError(msg)
    annotation = get_type_hints(func).get(parameters[0].name)
    if not isinstance(annotation, type | UnionType):
        msg = f"@step {name!r} needs a concrete payload type annotation"
        raise RitualDefinitionError(msg)
    return annotation


def source_text(func: Callable[..., Awaitable[Transition]]) -> str | None:
    try:
        return textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None


def step(func: Callable[..., Awaitable[Transition]]) -> Step:
    name = getattr(func, "__name__", "<step>")
    payload_type = _payload_type(func)

    async def run(payload: object) -> Transition:
        if not isinstance(payload, payload_type):
            msg = f"step {name!r} expected {payload_type}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await func(payload)

    return Step(name=name, run=run, input_type=payload_type, source=source_text(func))


def _components_model(func: Callable[..., Awaitable[Transition]]) -> type[BaseModel]:
    name = getattr(func, "__name__", "<ritual>")
    parameters = list(inspect.signature(func).parameters.values())
    if len(parameters) != 1:
        msg = f"@ritual {name!r} must take exactly one components parameter"
        raise RitualDefinitionError(msg)
    annotation = get_type_hints(func).get(parameters[0].name)
    if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        msg = f"@ritual {name!r} needs a pydantic model as its components type"
        raise RitualDefinitionError(msg)
    return annotation


def component_flags(components: type[BaseModel]) -> list[tuple[str, str, bool]]:
    flags: list[tuple[str, str, bool]] = []
    for name, field in components.model_fields.items():
        type_name: str = getattr(field.annotation, "__name__", "value")
        flags.append((name, type_name, field.is_required()))
    return flags


def ritual(name: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> Callable[..., Ritual]:
    def wrap(func: Callable[..., Awaitable[Transition]]) -> Ritual:
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
