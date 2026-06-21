import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, JsonValue, TypeAdapter

# --- cast lifecycle ---


class CastHello(BaseModel):
    kind: Literal["cast_hello"] = "cast_hello"
    cast_id: str
    project_root: str
    ritual: str
    components: dict[str, JsonValue]
    started_at: datetime


class CastGoodbye(BaseModel):
    kind: Literal["cast_goodbye"] = "cast_goodbye"
    cast_id: str
    status: Literal["ok", "error"]
    detail: str | None = None


class GrimoireBegin(BaseModel):
    kind: Literal["grimoire_begin"] = "grimoire_begin"
    cast_id: str


class GrimoireEnd(BaseModel):
    kind: Literal["grimoire_end"] = "grimoire_end"
    cast_id: str


# --- rite lifecycle ---


class RiteStarted(BaseModel):
    kind: Literal["rite_started"] = "rite_started"
    cast_id: str
    rite_id: str
    parent_id: str | None
    name: str
    category: Literal["step", "medium"]
    started_at: datetime


class RiteDelta(BaseModel):
    kind: Literal["rite_delta"] = "rite_delta"
    cast_id: str
    rite_id: str
    delta: str


class RiteFinished(BaseModel):
    kind: Literal["rite_finished"] = "rite_finished"
    cast_id: str
    rite_id: str
    status: Literal["ok", "error"]
    result: JsonValue | None = None
    finished_at: datetime


# --- prompts ---


class DecideRequested(BaseModel):
    kind: Literal["decide_requested"] = "decide_requested"
    cast_id: str
    rite_id: str
    request_id: str
    prompt: str
    options: list[str]


class DecideResolved(BaseModel):
    kind: Literal["decide_resolved"] = "decide_resolved"
    cast_id: str
    request_id: str
    choice: str


class ApprovalRequested(BaseModel):
    kind: Literal["approval_requested"] = "approval_requested"
    cast_id: str
    rite_id: str
    request_id: str
    prompt: str
    detail: JsonValue | None = None


class ApprovalResolved(BaseModel):
    kind: Literal["approval_resolved"] = "approval_resolved"
    cast_id: str
    request_id: str
    approved: bool


class AskRequested(BaseModel):
    kind: Literal["ask_requested"] = "ask_requested"
    cast_id: str
    rite_id: str
    request_id: str
    prompt: str
    choices: list[str] | None = None


class AskResolved(BaseModel):
    kind: Literal["ask_resolved"] = "ask_resolved"
    cast_id: str
    request_id: str
    answer: str


# --- locks ---


class LockAcquireRequested(BaseModel):
    kind: Literal["lock_acquire_requested"] = "lock_acquire_requested"
    cast_id: str
    request_id: str
    key: str


class LockGranted(BaseModel):
    kind: Literal["lock_granted"] = "lock_granted"
    cast_id: str
    request_id: str
    key: str
    token: str


class LockDenied(BaseModel):
    kind: Literal["lock_denied"] = "lock_denied"
    cast_id: str
    request_id: str
    key: str
    reason: str


class LockReleased(BaseModel):
    kind: Literal["lock_released"] = "lock_released"
    cast_id: str
    key: str
    token: str


WireMessage = (
    CastHello
    | CastGoodbye
    | GrimoireBegin
    | GrimoireEnd
    | RiteStarted
    | RiteDelta
    | RiteFinished
    | DecideRequested
    | DecideResolved
    | ApprovalRequested
    | ApprovalResolved
    | AskRequested
    | AskResolved
    | LockAcquireRequested
    | LockGranted
    | LockDenied
    | LockReleased
)

_MESSAGE_ADAPTER: TypeAdapter[WireMessage] = TypeAdapter(
    Annotated[WireMessage, Discriminator("kind")]
)


def encode_frame(message: WireMessage) -> bytes:
    return _MESSAGE_ADAPTER.dump_json(message) + b"\n"


def decode_frame(frame: str | bytes) -> WireMessage:
    return _MESSAGE_ADAPTER.validate_json(frame)


async def read_frames(reader: asyncio.StreamReader) -> AsyncIterator[WireMessage]:
    async for raw in reader:
        if stripped := raw.strip():
            yield decode_frame(stripped)
