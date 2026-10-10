from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator, JsonValue, TypeAdapter

# --- cast lifecycle ---


# A resumed cast is a new cast — new id, new journal — that says which one it is
# carrying on from. Recording it on the hello rather than beside it means the
# daemon, the journal and a surface all learn it from the same message.
class CastHello(BaseModel):
    kind: Literal["cast_hello"] = "cast_hello"
    cast_id: str
    project_root: str
    # The repository the cast belongs to, as its git common dir: every worktree
    # of one repository shares it, while `project_root` is the tree it runs in.
    project: str
    ritual: str
    components: dict[str, JsonValue]
    started_at: datetime
    resumed_from: str | None = None


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


# The daemon outlives every window on it, so ending it is a request of its own:
# `vekna stop` opens a connection with this and nothing else.
class StopRequested(BaseModel):
    kind: Literal["stop_requested"] = "stop_requested"


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


RiteEndStatus = Literal["ok", "error", "cancelled"]


class RiteFinished(BaseModel):
    kind: Literal["rite_finished"] = "rite_finished"
    cast_id: str
    rite_id: str
    status: RiteEndStatus
    result: JsonValue | None = None
    finished_at: datetime
    error: str | None = None


# --- prompts ---


# `rite_id` says which rite is asking, when one is — a surface groups the prompt
# under it. Optional because the answer never depends on it: the cast that asked
# is what a prompt has to be routed by, and that is `cast_id`.
class DecideRequested(BaseModel):
    kind: Literal["decide_requested"] = "decide_requested"
    cast_id: str
    rite_id: str | None = None
    request_id: str
    prompt: str
    options: list[str] | None = None
    free: bool = False


class DecideResolved(BaseModel):
    kind: Literal["decide_resolved"] = "decide_resolved"
    cast_id: str
    request_id: str
    answer: str


# The question stopped being asked without an answer: its rite was cancelled,
# or the channel raised. A surface still showing it would be waiting on nobody.
class DecideWithdrawn(BaseModel):
    kind: Literal["decide_withdrawn"] = "decide_withdrawn"
    cast_id: str
    request_id: str


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


# Everything a cast says about itself, and the one thing that does not. Split so
# that `cast_id` is a field of the type rather than something each consumer
# re-establishes: the daemon's hub, the journal and the debug log all take
# `CastMessage`, and the only place a `SurfaceHello` can arrive is the handshake
# that reads the first frame off a connection.
# A hello opens a cast and an update changes one already open, which is the
# split the daemon acts on: it looks the cast up for an update and has nothing
# to look up for a hello.
CastUpdate = (
    CastGoodbye
    | GrimoireBegin
    | GrimoireEnd
    | RiteStarted
    | RiteDelta
    | RiteFinished
    | DecideRequested
    | DecideResolved
    | DecideWithdrawn
    | LockAcquireRequested
    | LockGranted
    | LockDenied
    | LockReleased
)

CastMessage = CastHello | CastUpdate

# What a connection that is not a cast opens with, and only opens with: past the
# first frame there is nothing left for one of these to say.
Opening = SurfaceHello | StopRequested

WireMessage = CastMessage | Opening


# --- the record on disk ---

# `run.json`, beside the event log. It lives here rather than with the daemon's
# own types because it is shared exactly the way a message is: the daemon writes
# it, and a resumed cast process — which may not import the daemon's layers —
# reads it back to learn what it is carrying on.
CastStatus = Literal["running", "ok", "error", "disconnected"]


# `gapped` is what the event log cannot say for itself: an append the daemon
# could not make leaves the log short, and a log that lost its tail reads
# exactly like the log of a cast that was killed. The resume is the same either
# way — replay what landed, run live from there — so this is not a gate but the
# operator's answer to whether a run lost anything, and what a kept recording
# (issue #114) refuses to be made from.
class RunRecord(BaseModel):
    hello: CastHello
    status: CastStatus = "running"
    detail: str | None = None
    gapped: bool = False


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
