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
    # The components the caster named. A started cast records every component,
    # its defaults too, so this is what tells a flag from a default. `None` from
    # a cast that does not say: every key of `components` then counts as named.
    said: list[str] | None = None
    started_at: datetime
    resumed_from: str | None = None
    # Spawned by the daemon, so its prompts are answered over the wire. A cast
    # run by hand asks on its own terminal too.
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
    # The vigil whose interval started this cast: the daemon counts such casts
    # against `vigil_processes`.
    vigil: str | None = None
    # The process saying it, which is what the daemon signals when a cancel
    # asked over the wire is not acted on.
    pid: int | None = None


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
    # The operator marked the failure seen. Only the daemon says it, on the
    # goodbye it sends surfaces again for a `CastSeen`.
    seen: bool = False


# What a connection opens with is what it is. A cast says `CastHello`; anything
# watching says this, and is sent the live casts and everything they do next. No
# fields: a surface is not addressed, only fanned out to.
class SurfaceHello(BaseModel):
    kind: Literal["surface_hello"] = "surface_hello"


# The daemon outlives every window on it, so ending it is a request of its own:
# `vekna stop` opens a connection with this and nothing else.
class StopRequested(BaseModel):
    kind: Literal["stop_requested"] = "stop_requested"


# `vekna version`, and every vekna about to talk to a daemon, opens a connection
# with this and nothing else. A daemon that predates it reads no frame it knows
# and hangs up, which is an answer too.
class VersionRequested(BaseModel):
    kind: Literal["version_requested"] = "version_requested"


# Said back down the connection that asked, which then closes.
class DaemonVersion(BaseModel):
    kind: Literal["daemon_version"] = "daemon_version"
    version: str


# What a surface asks the daemon for, past its `SurfaceHello`: start a ritual in
# a directory. The components cross as the strings the operator typed — the
# daemon loads no ritual, so the cast it spawns is what validates them. A
# connection may open with one instead, and is answered a `CastQueued` naming
# the cast, or a `CastRefused`.
class CastRequested(BaseModel):
    kind: Literal["cast_requested"] = "cast_requested"
    project_root: str
    ritual: str
    components: dict[str, str]


# Said back to the surface that asked, and to nobody else: a request the daemon
# would not queue, or a cancel it could not pass on, is that operator's to hear
# about.
class CastRefused(BaseModel):
    kind: Literal["cast_refused"] = "cast_refused"
    reason: str


# A cast typed by hand opens a connection with this and nothing else before its
# first step, and is answered `CastAdmitted` or `CastRefused`. The daemon
# spawns nothing for it: the cast runs where it was typed, so all the daemon can
# do about a full machine is say so. A daemon that predates the question hangs
# up, and the cast runs.
class AdmissionRequested(BaseModel):
    kind: Literal["admission_requested"] = "admission_requested"
    project_root: str


class CastAdmitted(BaseModel):
    kind: Literal["cast_admitted"] = "cast_admitted"


# A window opens a connection with this and nothing else to mark a failed cast
# seen, or with `seen` false to take the mark back. Answered the cast's
# `CastGoodbye` carrying the mark, which every surface is sent too, or
# `CastRefused`. The daemon keeps the mark for as long as it holds the cast. A
# daemon that predates the question hangs up.
class CastSeen(BaseModel):
    kind: Literal["cast_seen"] = "cast_seen"
    cast_id: str
    seen: bool = True


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
# rebase left open. It stays out of the pool until `vekna altar fix` or somebody
# cleans it, and the cast that left it is who it is reported against.
class TreeBlocked(BaseModel):
    kind: Literal["tree_blocked"] = "tree_blocked"
    cast_id: str
    path: str
    reason: str


# The tree a cast left blocked was parked, by `vekna altar` or by a lease
# that found it clean: the block is over.
class TreeFreed(BaseModel):
    kind: Literal["tree_freed"] = "tree_freed"
    cast_id: str
    path: str


# `vekna altar` opens a connection with this and nothing else, and it is the
# only way a project's pool is made: a lease hands out a tree that was set up
# here and makes none. `reset` removes every tree no cast holds, `fix` cleans
# each, moves its parking branch to the base and sets it up again, `init` makes
# the trees the pool lacks and sets up each that never was. In that order when
# more than one is asked. With `save`, what a tree had not committed is kept on
# a branch of its own before a reset or a fix throws it away. With none of the
# three, nothing is touched and each tree is said as it stands. `tree` is the
# number of the one tree to act on, and `None` is every tree.
class AltarRequested(BaseModel):
    kind: Literal["altar_requested"] = "altar_requested"
    project_root: str
    reset: bool = False
    init: bool = False
    fix: bool = False
    save: bool = False
    tree: int | None = None


# What the altar says of one tree of the pool. This one is set up and on its
# parking branch. `saved` is the branch its uncommitted work went to, whether
# or not the tree then came right.
class ParkedTree(BaseModel):
    outcome: Literal["parked"] = "parked"
    path: str
    saved: str | None = None


# A running cast holds it, so it is left as it is.
class HeldTree(BaseModel):
    outcome: Literal["held"] = "held"
    path: str


class FailedTree(BaseModel):
    outcome: Literal["failed"] = "failed"
    path: str
    reason: str
    saved: str | None = None


# The tree and everything beside it is gone from disk and from git.
class RemovedTree(BaseModel):
    outcome: Literal["removed"] = "removed"
    path: str
    saved: str | None = None


# No cast holds it and no lease would hand it out: it was never set up, or it
# has work or an operation left open. Said only of a tree nothing was done to.
class BlockedTree(BaseModel):
    outcome: Literal["blocked"] = "blocked"
    path: str
    reason: str


TendedTree = Annotated[
    ParkedTree | HeldTree | FailedTree | RemovedTree | BlockedTree,
    Discriminator("outcome"),
]


# Said back down the connection that asked, which then closes.
class AltarTended(BaseModel):
    kind: Literal["altar_tended"] = "altar_tended"
    trees: list[TendedTree]


class GrimoireBegin(BaseModel):
    kind: Literal["grimoire_begin"] = "grimoire_begin"
    cast_id: str


class GrimoireEnd(BaseModel):
    kind: Literal["grimoire_end"] = "grimoire_end"
    cast_id: str


# --- the queue ---


# A cast asking the daemon to queue another. The enqueuing cast resolved the
# ritual, and the daemon, which loads no ritual, only checks the tree is there.
# The child's hello carries the components its enqueuer set and no others: the
# child answers the rest from its own defaults when it starts, and the hello it
# then says, every component resolved, replaces this one on the record.
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
    # What the call was given, cut to one line: a shell's command, an agent's
    # prompt. None from a step, and from a cast older than the field.
    summary: str | None = None


class RiteDelta(BaseModel):
    kind: Literal["rite_delta"] = "rite_delta"
    cast_id: str
    rite_id: str
    delta: str
    # Output for a window, not for the terminal that follows the cast.
    quiet: bool = False


# "error" raised; "reported" came back and said it had failed, a shell exiting
# non-zero, so what it recorded stands and a resume replays it.
RiteEndStatus = Literal["ok", "reported", "error", "cancelled"]


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
# is what a prompt has to be routed by, and that is `cast_id`. `reactions` names
# an emoji for an answer, for a surface that takes a tap as the answer; an
# answer it leaves out keeps the emoji that surface gives it.
class DecideRequested(BaseModel):
    kind: Literal["decide_requested"] = "decide_requested"
    cast_id: str
    rite_id: str | None = None
    request_id: str
    prompt: str
    options: list[str] | None = None
    free: bool = False
    reactions: dict[str, str] | None = None


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


# Who answers a prompt. Unclaimed, whichever answers first: the terminal of a
# cast typed by hand, the terminal following a spawned one, or any surface. A
# surface claims a prompt to take it over: every other answerer
# stops taking answers for it until `DecideReleased`. The id is how a surface
# tells its own claim from somebody else's.
class DecideClaimed(BaseModel):
    kind: Literal["decide_claimed"] = "decide_claimed"
    cast_id: str
    request_id: str
    claim_id: str


# The holder let the prompt go, or went away: whoever was answering before the
# claim answers again.
class DecideReleased(BaseModel):
    kind: Literal["decide_released"] = "decide_released"
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
    | DecideClaimed
    | DecideReleased
    | LockAcquireRequested
    | LockGranted
    | LockDenied
    | LockReleased
    | CodingSlotRequested
    | CodingSlotGranted
    | CodingSlotReleased
    | TreeBlocked
    | TreeFreed
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
Opening = (
    SurfaceHello
    | StopRequested
    | AltarRequested
    | VersionRequested
    | AdmissionRequested
    | CastSeen
)

# A request the daemon answers on a connection of its own, with one frame. Not in
# `Opening`: a surface sends `CastRequested` later in its connection too.
Asked = (
    AltarRequested | VersionRequested | CastRequested | AdmissionRequested | CastSeen
)

# Between a surface and the daemon, and never about a cast that exists yet.
Request = CastRequested | CastRefused | AltarTended | DaemonVersion | CastAdmitted


# A surface asking for a running cast to end, passed on by the daemon down the
# cast's own connection. The cast cancels itself, so its rites end cancelled and
# it says goodbye like any cast that failed, rather than vanishing mid-write.
class CastCancelRequested(BaseModel):
    kind: Literal["cast_cancel_requested"] = "cast_cancel_requested"
    cast_id: str


WireMessage = CastMessage | Opening | Request | CastCancelRequested


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
