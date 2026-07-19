from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, JsonValue

from vekna.lexicon import RitualError


class CodingOutputError(RitualError):
    pass


class CodingOpts(BaseModel):
    model: str | None = None
    system: str | None = None
    cwd: str | None = None


class CodingResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None


class FocusReply(BaseModel):
    text: str
    structured: JsonValue | None = None
    telemetry: dict[str, JsonValue] = {}


GateFn = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class CodingCall:
    prompt: str
    opts: CodingOpts
    output_schema: dict[str, JsonValue] | None
    focus_options: object | None


class CodingFocusProtocol(Protocol):
    async def run(
        self, call: CodingCall, *, on_delta: Callable[[str], None], gate: GateFn | None
    ) -> FocusReply: ...
