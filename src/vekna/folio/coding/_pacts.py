from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingSessionError(RitualError):
    pass


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


class CodingResult(BaseModel):
    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
