import inspect
from collections.abc import Callable
from types import NoneType, UnionType
from typing import Annotated, Any, TypeGuard, get_args, get_type_hints

from pydantic import BaseModel

from vekna.lexicon._pacts import RitualDefinitionError

_NAMELESS = "value"


# What this module reflects over: past the boundary check the payload is a
# BaseModel and nothing more, because the type it was checked against is a
# runtime value read off an annotation. The return is `object` because nothing
# here calls the function — a signature and a `__name__` are the whole need, and
# what a body hands back is the caller's business, in `dispatch`.
_Erased = Callable[[BaseModel], object]


# 3.14 merged `typing.Union` into `types.UnionType`. Before it, `|` yields the
# typing union whenever a member is an Annotated alias — so `File | None` is a
# `UnionType` on 3.14 but a `_UnionGenericAlias` on 3.11, where an isinstance
# check misses it and the flag rendered `<Optional>`. What both spellings share
# is `__origin__`, and the sentinel is taken from an example rather than named:
# the name is the very thing 3.14 merged away and the linters ask you to drop.
_UNION_ORIGIN = getattr(Annotated[int, "example"] | None, "__origin__", None)


def _component_flags(components: type[BaseModel]) -> list[tuple[str, str, bool]]:
    return [
        (name, _type_name(field.annotation), field.is_required())
        for name, field in components.model_fields.items()
    ]


# The one place a runtime annotation is narrowed, so the reflection boundary's
# exemptions stay at two lines rather than spreading through every caller.
def _as_model(annotation: type[Any] | UnionType | None) -> type[BaseModel] | None:
    if not isinstance(annotation, type):
        return None
    if issubclass(annotation, BaseModel):
        return annotation
    return None


def _components_model(func: _Erased) -> type[BaseModel]:
    annotation = _sole_annotation(func, decorator="ritual", noun="components")
    if (model := _as_model(annotation)) is not None:
        return model
    msg = f"@ritual {func.__name__!r} needs a pydantic model as its components type"
    raise RitualDefinitionError(msg)


def _is_model_union(annotation: type[Any] | UnionType | None) -> TypeGuard[UnionType]:
    if not isinstance(annotation, UnionType):
        return False

    return all(
        _as_model(member) is not None or member is NoneType
        for member in get_args(annotation)
    )


def _is_union(annotation: type[Any] | UnionType | None) -> bool:
    if isinstance(annotation, UnionType):
        return True
    origin = getattr(annotation, "__origin__", None)
    return origin is not None and origin is _UNION_ORIGIN


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


# Naming an annotation means reading an attribute off whatever the author wrote.
# `name: str` is what keeps that untyped read from spreading: everything below
# narrows by isinstance, as the rest of this module does.
def _plain_name(annotation: type[Any] | UnionType | None) -> str:
    name = getattr(annotation, "__name__", None)
    return name if isinstance(name, str) else _NAMELESS


def _sole_annotation(func: _Erased, *, decorator: str, noun: str) -> Any | None:
    parameters = list(inspect.signature(func).parameters.values())
    if len(parameters) != 1:
        msg = f"@{decorator} {func.__name__!r} must take exactly one {noun} parameter"
        raise RitualDefinitionError(msg)
    return get_type_hints(func).get(parameters[0].name)


# Two wrappers hide the name a flag should print, and both arrive by way of an
# optional component. A union has no `__name__` worth printing — `str | None`
# rendered `<Union>` on 3.14 and raised AttributeError on 3.11, and
# `File | None` called itself `<Optional>`. And pydantic unwraps a bare
# `Annotated[Path, ...]` into metadata, but inside a union it does not, so
# `File | None` rendered `<Annotated>`. An optional `--only` takes a Path;
# saying so is the whole point of printing a type at all.
def _type_name(annotation: type[Any] | UnionType | None) -> str:
    if _is_union(annotation):
        members = get_args(annotation)
        named = [_type_name(member) for member in members if member is not NoneType]
        return "|".join(named) or _NAMELESS
    # `__metadata__` is what makes an alias Annotated; its first arg is the type
    # underneath.
    if hasattr(annotation, "__metadata__"):
        wrapped = get_args(annotation)
        return _type_name(wrapped[0])
    return _plain_name(annotation)
