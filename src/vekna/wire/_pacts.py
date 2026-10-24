from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    TypeAdapter,
)

# --- cast lifecycle ---


# A resumed cast is a new cast — new id, new journal — that says which one it is
# carrying on from. Recording it on the hello rather than beside it means the
# daemon, the journal and a surface all learn it from the same message.
class CastHello(BaseModel):
    model_config = ConfigDict(validate_by_name=True)

    kind: Literal["cast_hello"] = "cast_hello"
    cast_id: str
    project_root: str
    # The repository the cast belongs to, as its git common dir: every worktree
    # of one repository shares it, while `project_root` is the tree it runs in.
    # A record written before casts carried it still reads and resumes, grouped
    # by the tree it ran in: what `project_of` answers outside git.
    project: str = Field(validation_alias=AliasChoices("project", "project_root"))
    ritual: str
    components: dict[str, JsonValue]
    started_at: datetime
    resumed_from: str | None = None
    # Spawned by the daemon, so its prompts are answered over the wire. A cast
    # run by hand answers on its own terminal and nowhere else.
    wired: bool = False
    # Cast with `--unattended`: every `decide` refused. Kept so a cast carried
    # on later is unattended still, whatever the carrying-on command says.
    unattended: bool = False
    # The cast whose `enqueue` made this one. What a sweep spawned is a query
    # over the journal, not a list anybody keeps.
    enqueued_by: str | None = None
    # Said by the enqueuing cast, which has the ritual: the daemon leases a tree
    # before the first spawn instead of learning the need from `NEEDS_TREE`.
    worktree: bool = False


# `disconnected` is the daemon's own word for a cast whose socket closed without
# one of these: it is a final status like the other two, and spelling it here is
# what lets a peer surface learn it the same way it learns everything else.
class CastGoodbye(BaseModel):
    kind: Literal["cast_goodbye"] = "cast_goodbye"
    cast_id: str
    status: Literal["ok", "error", "disconnected"]
    detail: str | None = None
    # The ritual's return model as JSON, for a cast that awaits this one. The
    # daemon relays it; the awaiting cast validates it, having the lexicon.
    result: JsonValue | None = None


# What a connection opens with is what it is. A cast says `CastHello`; anything
# watching says this, and is sent the live casts and everything they do next. No
# fields: a surface is not addressed, only fanned out to.
class SurfaceHello(BaseModel):
    kind: Literal["surface_hello"] = "surface_hello"


# The daemon outlives every window on it, so ending it is a request of its own:
# `vekna stop` opens a connection with this and nothing else.
class StopRequested(BaseModel):
    kind: Literal["stop_requested"] = "stop_requested"


# What a surface asks the daemon for, past its `SurfaceHello`: start a ritual in
# a directory. The components cross as the strings the operator typed — the
# daemon loads no ritual, so the cast it spawns is what validates them.
class CastRequested(BaseModel):
    kind: Literal["cast_requested"] = "cast_requested"
    project_root: str
    ritual: str
    components: dict[str, str]


# Said back to the surface that asked, and to nobody else: a request the daemon
# would not queue is that operator's to hear about.
class CastRefused(BaseModel):
    kind: Literal["cast_refused"] = "cast_refused"
    reason: str


# A cast the daemon has a record of and no process for yet: it waits for a
# process slot, and the hello before it was written by the daemon, not the cast.
class CastQueued(BaseModel):
    kind: Literal["cast_queued"] = "cast_queued"
    cast_id: str


# How a spawned cast whose ritual runs in a worktree says it was spawned without
# one: it exits with this before its hello, and the daemon queues it again for a
# slot and a tree. Only the cast knows its ritual, and the daemon loads none.
# EX_TEMPFAIL: try again later.
NEEDS_TREE = 75


# The tree a cast ran in was not parked after it: uncommitted work, or a merge or
# rebase left open. Nothing resets it, so it stays out of the pool until somebody
# cleans it, and the cast that left it is who it is reported against.
class TreeBlocked(BaseModel):
    kind: Literal["tree_blocked"] = "tree_blocked"
    cast_id: str
    path: str
    reason: str


class GrimoireBegin(BaseModel):
    kind: Literal["grimoire_begin"] = "grimoire_begin"
    cast_id: str


class GrimoireEnd(BaseModel):
    kind: Literal["grimoire_end"] = "grimoire_end"
    cast_id: str


# --- the queue ---


# A cast asking the daemon to queue another. The child's hello is whole: the
# enqueuing cast resolved the ritual and dumped the components, and the daemon,
# which loads no ritual, only checks the tree is there.
class EnqueueRequested(BaseModel):
    kind: Literal["enqueue_requested"] = "enqueue_requested"
    cast_id: str
    request_id: str
    hello: CastHello


class EnqueueAccepted(BaseModel):
    kind: Literal["enqueue_accepted"] = "enqueue_accepted"
    cast_id: str
    request_id: str


class EnqueueRefused(BaseModel):
    kind: Literal["enqueue_refused"] = "enqueue_refused"
    cast_id: str
    request_id: str
    reason: str


# The cast stops counting against its project's processes until `child` ends,
# and keeps its tree: its checkout has to be there when it carries on.
class AwaitRequested(BaseModel):
    kind: Literal["await_requested"] = "await_requested"
    cast_id: str
    request_id: str
    child: str


# Sent once a slot is free again, so a parent coming back never runs its
# project past `processes`.
class AwaitEnded(BaseModel):
    kind: Literal["await_ended"] = "await_ended"
    cast_id: str
    request_id: str
    child: str
    status: Literal["ok", "error", "disconnected"]
    detail: str | None = None
    result: JsonValue | None = None


# The wait was cancelled. The child is not: it was queued to be run.
class AwaitWithdrawn(BaseModel):
    kind: Literal["await_withdrawn"] = "await_withdrawn"
    cast_id: str
    request_id: str


EnqueueMessage = EnqueueRequested | EnqueueAccepted | EnqueueRefused
AwaitMessage = AwaitRequested | AwaitEnded | AwaitWithdrawn


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


# --- coding slots ---


# How many agent sessions run at once across every cast on the account. A cast
# asks before each coding call and says when it is done; the daemon grants in
# the order asked. The daemon sends the grant, a cast sends the other two.
class CodingSlotRequested(BaseModel):
    kind: Literal["coding_slot_requested"] = "coding_slot_requested"
    cast_id: str
    request_id: str


class CodingSlotGranted(BaseModel):
    kind: Literal["coding_slot_granted"] = "coding_slot_granted"
    cast_id: str
    request_id: str


class CodingSlotReleased(BaseModel):
    kind: Literal["coding_slot_released"] = "coding_slot_released"
    cast_id: str
    request_id: str


CodingSlotMessage = CodingSlotRequested | CodingSlotGranted | CodingSlotReleased


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
    | CastQueued
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
    | CodingSlotRequested
    | CodingSlotGranted
    | CodingSlotReleased
    | TreeBlocked
    | EnqueueRequested
    | EnqueueAccepted
    | EnqueueRefused
    | AwaitRequested
    | AwaitEnded
    | AwaitWithdrawn
)

CastMessage = CastHello | CastUpdate

# What a connection that is not a cast opens with, and only opens with: past the
# first frame there is nothing left for one of these to say.
Opening = SurfaceHello | StopRequested

# Between a surface and the daemon, and never about a cast that exists yet.
Request = CastRequested | CastRefused

WireMessage = CastMessage | Opening | Request


# --- the record on disk ---

# `run.json`, beside the event log. It lives here rather than with the daemon's
# own types because it is shared exactly the way a message is: the daemon writes
# it, and a resumed cast process — which may not import the daemon's layers —
# reads it back to learn what it is carrying on.
CastStatus = Literal["queued", "running", "ok", "error", "disconnected"]


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
    result: JsonValue | None = None


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
