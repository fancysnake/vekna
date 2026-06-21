import inspect
from collections.abc import Awaitable, Callable
from types import UnionType
from typing import Any, get_type_hints

from pydantic import BaseModel, create_model

from ._pacts import Ritual, RitualDefinitionError, Step, StepBoundaryError, Transition
from ._specs import DEFAULT_MAX_STEPS


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


def step(func: Callable[..., Awaitable[Transition]]) -> Step:
    name = getattr(func, "__name__", "<step>")
    payload_type = _payload_type(func)

    async def run(payload: object) -> Transition:
        if not isinstance(payload, payload_type):
            msg = f"step {name!r} expected {payload_type}, got {type(payload).__name__}"
            raise StepBoundaryError(msg)
        return await func(payload)

    return Step(name=name, run=run, input_type=payload_type)


def _component_model(func: Callable[..., Awaitable[Transition]]) -> type[BaseModel]:
    hints = get_type_hints(func)
    fields: dict[str, Any] = {}
    for parameter in inspect.signature(func).parameters.values():
        annotation = hints.get(parameter.name, object)
        default = (
            ... if parameter.default is inspect.Parameter.empty else parameter.default
        )
        fields[parameter.name] = (annotation, default)
    name = getattr(func, "__name__", "ritual")
    return create_model(f"{name}_components", **fields)


def ritual(name: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> Callable[..., Ritual]:
    def wrap(func: Callable[..., Awaitable[Transition]]) -> Ritual:
        model = _component_model(func)
        field_names = list(model.model_fields)

        async def run(values: BaseModel) -> Transition:
            return await func(
                **{field: getattr(values, field) for field in field_names}
            )

        return Ritual(name=name, components=model, run=run, max_steps=max_steps)

    return wrap
