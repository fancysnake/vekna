from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingSessionError(RitualError):
    pass


# Half-closed on purpose: two reserved words plus any thread name the author
# invents, which is why the parameter takes `Session | str`. StrEnum is what
# makes the two spellings meet — `"continue" == Session.CONTINUE` — so an author
# who types the string and one who reaches for the member land in one branch.
# Reserved means these two exact spellings: `"New"` is a thread named "New", on
# purpose. Folding case would take the capitalised forms out of an author's
# hands to buy a rule harder to hold than a set of two literal strings.
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
