from enum import StrEnum

from pydantic import BaseModel

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingSessionError(RitualError):
    pass


# Half-closed on purpose: two reserved words plus any thread name the author
# invents, which is why the parameter takes `Session | str`. StrEnum is what
# makes the two spellings meet — `"continue" == Session.CONTINUE` — so an author
# who types the string and one who reaches for the member land in one branch.
class Session(StrEnum):
    NEW = "new"
    CONTINUE = "continue"


# Every knob here is portable: it means the same thing whichever Focus answers
# the call. Focus-specific ones travel separately, as `focus_options`.
class CodingOpts(BaseModel):
    model: str | None = None
    system: str | None = None
    cwd: str | None = None
    gate_tools: list[str] | None = None
    session: Session | str = Session.NEW


class CodingResult(BaseModel):
    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None
