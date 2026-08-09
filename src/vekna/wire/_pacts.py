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


# `disconnected` is the daemon's own word for a cast whose socket closed without
# one of these: it is a final status like the other two, and spelling it here is
# what lets a peer surface learn it the same way it learns everything else.
class CastGoodbye(BaseModel):
    kind: Literal["cast_goodbye"] = "cast_goodbye"
    cast_id: str
    status: Literal["ok", "error", "disconnected"]
    detail: str | None = None


# What a connection opens with is what it is. A cast says `CastHello`; anything
# watching says this, and is sent the live casts and everything they do next. No
# fields: a surface is not addressed, only fanned out to.
class SurfaceHello(BaseModel):
    kind: Literal["surface_hello"] = "surface_hello"


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
    options: list[str] | None = None
    free: bool = False


class DecideResolved(BaseModel):
    kind: Literal["decide_resolved"] = "decide_resolved"
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
    | SurfaceHello
    | GrimoireBegin
    | GrimoireEnd
    | RiteStarted
    | RiteDelta
    | RiteFinished
    | DecideRequested
    | DecideResolved
    | LockAcquireRequested
    | LockGranted
    | LockDenied
    | LockReleased
)


# --- framing ---

# The codec sits with the messages it encodes: it is the serialised form of
# these DTOs, not logic about them. Keeping it here leaves the reader in
# `_links` importing only this module.

_MESSAGE_ADAPTER: TypeAdapter[WireMessage] = TypeAdapter(
    Annotated[WireMessage, Discriminator("kind")]
)


def encode_frame(message: WireMessage) -> bytes:
    return _MESSAGE_ADAPTER.dump_json(message) + b"\n"


def decode_frame(frame: str | bytes) -> WireMessage:
    return _MESSAGE_ADAPTER.validate_json(frame)
