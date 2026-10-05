import inspect
from collections.abc import Awaitable, Callable, Coroutine
from types import NoneType, UnionType
from typing import Annotated, Any, get_args, get_origin, get_type_hints

from pydantic import BaseModel

from vekna.lexicon._pacts import Done, Failure, Goto, RitualDefinitionError

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


def _model_members(
    annotation: type[Any] | UnionType | None, *, allow_none: bool = False
) -> tuple[type[BaseModel], ...] | None:
    if not isinstance(annotation, UnionType):
        return None
    members: list[type[BaseModel]] = []
    for arg in get_args(annotation):
        if allow_none and arg is NoneType:
            continue
        if (model := _as_model(arg)) is None:
            return None
        members.append(model)
    return tuple(members)


def _is_union(annotation: type[Any] | UnionType | None) -> bool:
    if isinstance(annotation, UnionType):
        return True
    origin = getattr(annotation, "__origin__", None)
    return origin is not None and origin is _UNION_ORIGIN


# A step may admit more than one payload shape — `Lint | Coverage` for a step
# two others transition into — so a union is legal here where a ritual's
# components, being one CLI interface, are not. A payload is the next step, so
# `None` is not one — except on the legacy path, where `Work | None` was what a
# bare `goto(target)` fed.
def _payloads(func: _Erased, *, legacy: bool = False) -> tuple[type[BaseModel], ...]:
    annotation = _sole_annotation(func, decorator="step", noun="payload")
    if (model := _as_model(annotation)) is not None:
        return (model,)
    if (members := _model_members(annotation, allow_none=legacy)) is not None:
        return members
    msg = (
        f"@step {func.__name__!r} needs a pydantic model, or a union of them, "
        "as its payload type"
    )
    raise RitualDefinitionError(msg)


# ponytail: whether a legacy step declared `Work | None`, so the payload a bare
# `goto(target)` leaves absent still reaches it. Delete with the shim.
def _optional_payload(func: _Erased) -> bool:
    annotation = _sole_annotation(func, decorator="step", noun="payload")
    return _is_union(annotation) and NoneType in get_args(annotation)


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


# The exits a body declares: the payload classes it may return, and whether it
# may return `Done`. `Done[T]` is only ever a return, so its `T` goes unread
# here — mypy is the one that checks it. None for the legacy `-> Transition`,
# recognisable by `Goto` among its members: it declares nothing, and `goto`
# names its targets at runtime. `BaseModel` is not that marker — a body
# annotated `-> BaseModel` declares an exit no step takes, which `check_exits`
# says so about.
def _exits(
    func: _Erased, *, decorator: str
) -> tuple[tuple[type[BaseModel], ...] | None, bool]:
    annotation = get_type_hints(func).get("return")
    # A body may be `def` handing back an awaitable, so the transition is under
    # one wrapper at most.
    if get_origin(annotation) in {Awaitable, Coroutine}:
        annotation = get_args(annotation)[-1]
    members = get_args(annotation) if _is_union(annotation) else (annotation,)
    if Goto in members:
        return None, True
    exits: list[type[BaseModel]] = []
    ends = False
    for member in members:
        if get_origin(member) is Done:
            ends = True
        elif (model := _as_model(member)) is not None:
            exits.append(model)
        elif member is Done:
            # The first thing a migrating author writes, and the generic is the
            # whole point: a ritual's result type is stated rather than erased.
            msg = (
                f"@{decorator} {func.__name__!r} returns a bare Done: name what it "
                "carries — Done[None] for a body that ends with no result"
            )
            raise RitualDefinitionError(msg)
        else:
            # A body with no return annotation has no member to name.
            named = "" if member is None else f", not {_type_name(member)}"
            msg = (
                f"@{decorator} {func.__name__!r} must declare its exits: "
                f"a return annotation naming step payloads and Done[...]{named}"
            )
            raise RitualDefinitionError(msg)
    return tuple(exits), ends


# `Failure[...]` over a class read at runtime, which a subscript cannot spell:
# the type checker wants a type there, not a value. pydantic hands back one
# cached class per payload, so routing by it is exact.
def _failure_of(payload: type[BaseModel]) -> type[Failure[BaseModel]]:
    erased: Any = Failure
    made: type[Failure[BaseModel]] = erased[payload]
    return made
