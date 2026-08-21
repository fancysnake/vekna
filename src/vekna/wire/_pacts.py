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
    ritual: str
    components: dict[str, JsonValue]
    started_at: datetime
    resumed_from: str | None = None
    # The lich that spawned this cast, absent for one run by hand. One field, and
    # what it buys is that a lich's history is a query over `runs/` rather than a
    # list something has to maintain.
    lich: str | None = None


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


# The end of a replay, said to the surface that just attached. A surface that
# paints forever does not need it; one that asks a question and exits — `vekna
# liches` — does, and the alternative is a timeout pretending to be an answer.
class SurfaceReady(BaseModel):
    kind: Literal["surface_ready"] = "surface_ready"


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


# --- what the ritual says it is doing ---


# The author's own line, set with `status()`. Cast-level and so no `rite_id`;
# empty text is how a ritual clears it. A surface with a frame pins the latest
# one; a surface that is a stream prints it as it arrives.
class CastStatus(BaseModel):
    kind: Literal["cast_status"] = "cast_status"
    cast_id: str
    text: str
    at: datetime


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


# --- liches ---


# The third kind of connection, and what one opens with. `pid` is here and not
# in the phylactery on purpose: it is true only while this socket is open, which
# is exactly as long as this message is worth anything.
class LichRose(BaseModel):
    kind: Literal["lich_rose"] = "lich_rose"
    lich: str
    root: str
    pid: int


# Sent by a lich that is dismissed, and synthesised by the daemon for one whose
# socket closed without saying anything — the same rule a cast's goodbye
# follows, and for the same reason: a station the daemon still believes in is a
# station commands are routed into the dark.
class LichFell(BaseModel):
    kind: Literal["lich_fell"] = "lich_fell"
    lich: str
    reason: Literal["dismissed", "disconnected"]


# Idle, or casting — the lich's own sentence about itself, which is not the
# ritual's (`CastStatus`). A surface shows both: this one, then the ritual's
# under it.
class LichStatus(BaseModel):
    kind: Literal["lich_status"] = "lich_status"
    lich: str
    ritual: str | None = None
    cast_id: str | None = None
    since: datetime | None = None


# Surface → daemon → lich. The daemon drops the row and the lich ends itself:
# both halves are needed, because the row outliving the process is what makes a
# lich dormant rather than gone, and this is the one command that means gone.
class LichDismissRequested(BaseModel):
    kind: Literal["lich_dismiss_requested"] = "lich_dismiss_requested"
    lich: str


# Surface → daemon → lich: start this. `argv` is what `vekna cast` is handed,
# because that is what the lich spawns — a ritual and its component flags, or
# `--prompt` and a line of text. Shaping it into fields would be this protocol
# learning the cast CLI's own grammar twice.
class CastRequested(BaseModel):
    kind: Literal["cast_requested"] = "cast_requested"
    lich: str
    argv: list[str]


# Lich → daemon → surface: not while that one runs. The facts, not the
# sentence — a surface says it in its own words, and a channel with buttons
# will not say it the way a terminal does.
class CastRefused(BaseModel):
    kind: Literal["cast_refused"] = "cast_refused"
    lich: str
    ritual: str
    since: datetime


class CastKillRequested(BaseModel):
    kind: Literal["cast_kill_requested"] = "cast_kill_requested"
    lich: str


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
    | CastStatus
    | DecideRequested
    | DecideResolved
    | LockAcquireRequested
    | LockGranted
    | LockDenied
    | LockReleased
)

CastMessage = CastHello | CastUpdate

# The same split one station over: a rising opens the connection, and everything
# after it is about a lich the daemon already holds.
LichUpdate = LichStatus | LichFell | CastRefused

LichMessage = LichRose | LichUpdate

# What a surface is allowed to *say*, as opposed to be sent. Until 0.8.0 a
# surface only listened; a lich takes orders, so this is the direction that
# opens — as far as the lich needs and no further. Every one of these names the
# lich it is for, because the daemon routes them by name and by nothing else.
SurfaceCommand = LichDismissRequested | CastRequested | CastKillRequested

WireMessage = CastMessage | SurfaceHello | SurfaceReady | LichMessage | SurfaceCommand


# --- the record on disk ---

# `run.json`, beside the event log. It lives here rather than with the daemon's
# own types because it is shared exactly the way a message is: the daemon writes
# it, and a resumed cast process — which may not import the daemon's layers —
# reads it back to learn what it is carrying on.
RunStatus = Literal["running", "ok", "error", "disconnected"]


# `gapped` is what a resume has to know that the event log cannot say for
# itself: an append the daemon could not make leaves a hole a reader cannot see,
# because a log missing a rite reads exactly like a log that never had one. A
# cast resumed across that hole re-runs the medium whose result fell in it —
# the shell command, the agent call — so the answer is to refuse instead.
class RunRecord(BaseModel):
    hello: CastHello
    status: RunStatus = "running"
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
