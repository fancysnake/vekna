from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingSessionError(RitualError):
    pass


class CodingOptsError(RitualError):
    pass


_MOVED = frozenset({"session", "key"})
_MOVED_HINT = "session and key are parameters of coding(), not fields of CodingOpts"


def _where(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(part) for part in loc) or "the bundle"


# The two halves of the declaration are the whole reason `forbid` is on, so the
# refusal names where they went. Anything else pydantic rejected is quoted as it
# came: a `RitualError` either way, because a mis-built bundle is an author's
# mistake in a file only they decide to type-check, and the cast should say so
# rather than unwind through the engine's frames. Reading `errors()` is what
# this module's `disallow_any_expr` exemption is for — pydantic's report is a
# list of TypedDicts whose values are `Any`, and it stops here.
def _refusal(*, bundle: str, error: ValidationError) -> str:
    details = error.errors()
    extras = [
        str(detail["loc"][0])
        for detail in details
        if detail["type"] == "extra_forbidden" and detail["loc"]
    ]
    if extras:
        named = ", ".join(repr(name) for name in extras)
        field = "no field" if len(extras) == 1 else "no fields"
        moved = f" — {_MOVED_HINT}" if _MOVED.intersection(extras) else ""
        return f"{bundle} has {field} {named}{moved}"
    # Reassembled rather than quoted whole: inside a wrap validator pydantic
    # titles its own report `ValidatorCallable`, which names an implementation
    # detail of this refusal instead of the model the author was building.
    said = "; ".join(f"{_where(detail['loc'])}: {detail['msg']}" for detail in details)
    return f"{bundle} refused what it was given — {said}"


# Closed, and only two words wide: whether this call resumes. *Which* thread it
# resumes is `key`, a separate parameter, because a set that held both would be
# a type no checker could close — the shape that let `session=None` through as a
# thread named "None". StrEnum so the plain spelling still lands on the member:
# `Session("continue")` is `Session.CONTINUE`, and `Session("New")` raises,
# which is the same refusal an author gets for any other word.
class Session(StrEnum):
    NEW = "new"
    CONTINUE = "continue"


# What bundles here is *configuration*: reusing one `CodingOpts` across calls is
# harmless, which is the point of bundling it. Per-call identity is not — the
# thread a call joins stays a parameter of `coding` itself, and `forbid` is what
# makes that visible, since the old `CodingOpts(session=...)` spelling raises
# rather than being quietly dropped onto whatever thread the call defaults to.
# Portability is a property of the fields rather than the bundle: every knob but
# `focus_options` means the same thing whichever Focus answers, and that one is
# read by the Focus it was built for and ignored by any other.
class CodingOpts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    system: str | None = None
    cwd: str | None = None
    gate_tools: list[str] | None = None
    focus_options: BaseModel | None = None

    # Wrapping the model's own validation rather than overriding `__init__`,
    # which would have to spell every field a second time to stay typed — and a
    # second spelling of the field list is the drift this bundle exists to
    # avoid. `CodingOptsError` is not a `ValueError`, so pydantic lets it past
    # rather than folding it back into a `ValidationError`.
    @model_validator(mode="wrap")
    @classmethod
    def _refuse_unknown(
        cls, values: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(values)
        except ValidationError as error:
            raise CodingOptsError(_refusal(bundle=cls.__name__, error=error)) from error


class CodingResult(BaseModel):
    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
