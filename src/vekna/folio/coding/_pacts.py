from pydantic import BaseModel

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingOpts(BaseModel):
    model: str | None = None
    system: str | None = None
    cwd: str | None = None


class CodingResult(BaseModel):
    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None


class PromptOutput(BaseModel):
    output: str
