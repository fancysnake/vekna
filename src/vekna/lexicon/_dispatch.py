import ast
import importlib
import importlib.util
import inspect
import sys
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import UnionType
from typing import Any, ParamSpec, TypeVar, get_type_hints

from pydantic import BaseModel, create_model

from ._mills import Compendium, medium_rite
from ._pacts import Ritual, RitualDefinitionError, Step, StepBoundaryError, Transition
from ._specs import DEFAULT_MAX_STEPS

_P = ParamSpec("_P")
_MediumT = TypeVar("_MediumT")


def medium(
    func: Callable[_P, Awaitable[_MediumT]],
) -> Callable[_P, Awaitable[_MediumT]]:
    name = getattr(func, "__name__", "medium")

    async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _MediumT:
        async with medium_rite(name):
            return await func(*args, **kwargs)

    return wrapped


if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


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

    return Step(name=name, run=run, input_type=payload_type, source=source_text(func))


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


_GOTO = "goto"
_DONE = "done"
# Labels for the two nodes that are not steps: where a cast enters, and where
# it leaves.
START = "(start)"
ENDS = "(done)"


def source_text(func: Callable[..., Awaitable[Transition]]) -> str | None:
    try:
        return textwrap.dedent(inspect.getsource(func))
    except (OSError, TypeError):
        return None


# Best-effort and deliberately shallow: the graph is read off the source text,
# so a `goto` whose target is computed rather than named simply does not show
# up. Running the ritual remains the only way to know for certain.
def _transitions(source: str | None) -> list[str]:
    if source is None:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    targets: list[str] = []
    ends = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id == _DONE:
            ends = True
        elif node.func.id == _GOTO and node.args:
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id not in targets:
                targets.append(target.id)
    return [*targets, ENDS] if ends else targets


def _walk(
    *,
    compendium: Compendium,
    label: str,
    source: str | None,
    seen: set[str],
    graph: list[tuple[str, list[str]]],
) -> None:
    targets = _transitions(source)
    graph.append((label, targets))
    for target in targets:
        # A target the compendium never saw is a leaf: it is named here but
        # its own transitions cannot be read.
        if target in seen or (found := compendium.step(target)) is None:
            continue
        seen.add(target)
        _walk(
            compendium=compendium,
            label=target,
            source=found.source,
            seen=seen,
            graph=graph,
        )


def step_graph(
    compendium: Compendium, the_ritual: Ritual
) -> list[tuple[str, list[str]]]:
    graph: list[tuple[str, list[str]]] = []
    _walk(
        compendium=compendium,
        label=START,
        source=the_ritual.source,
        seen={START},
        graph=graph,
    )
    return graph


def component_flags(components: type[BaseModel]) -> list[tuple[str, str, bool]]:
    flags: list[tuple[str, str, bool]] = []
    for name, field in components.model_fields.items():
        type_name: str = getattr(field.annotation, "__name__", "value")
        flags.append((name, type_name, field.is_required()))
    return flags


def ritual(name: str, *, max_steps: int = DEFAULT_MAX_STEPS) -> Callable[..., Ritual]:
    def wrap(func: Callable[..., Awaitable[Transition]]) -> Ritual:
        model = _component_model(func)
        field_names = list(model.model_fields)

        async def run(values: BaseModel) -> Transition:
            return await func(
                **{field: getattr(values, field) for field in field_names}
            )

        return Ritual(
            name=name,
            components=model,
            run=run,
            max_steps=max_steps,
            source=source_text(func),
        )

    return wrap


def _register_rituals(compendium: Compendium, namespace: dict[str, object]) -> None:
    for value in namespace.values():
        if isinstance(value, Ritual):
            compendium.register(value)
        elif isinstance(value, Step):
            compendium.register_step(value)


def load_rituals_file(compendium: Compendium, path: Path) -> None:
    spec = importlib.util.spec_from_file_location("vekna_rituals", path)
    if spec is None or spec.loader is None:
        msg = f"cannot import rituals from {path}"
        raise RitualDefinitionError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _register_rituals(compendium, vars(module))


def load_rituals_module(compendium: Compendium, name: str) -> None:
    _register_rituals(compendium, vars(importlib.import_module(name)))


def read_config(path: Path) -> tuple[list[str], list[str]]:
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    section = data.get("rituals", {})
    if not isinstance(section, dict):
        return [], []
    modules = [m for m in section.get("modules", []) if isinstance(m, str)]
    files = [f for f in section.get("files", []) if isinstance(f, str)]
    return modules, files
