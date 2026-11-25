from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePath
from typing import Literal, Protocol

from vekna.wire import (
    AwaitRequested,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastStatus,
    DecideRequested,
    RiteEndStatus,
    RiteFinished,
    RiteStarted,
    RunRecord,
    TreeBlocked,
    WireMessage,
)

RiteStatus = Literal["running"] | RiteEndStatus


# A run directory whose record cannot be read back — torn, cut mid-character,
# refused by the disk, or never written at all. The id is the directory's name
# and the time is the directory's, because nothing else about it is known. Not
# on the wire: a resume refuses it, and only the journal and `vekna log` meet it.
@dataclass(frozen=True)
class DamagedRun:
    cast_id: str
    seen_at: datetime


Run = RunRecord | DamagedRun


def run_cast_id(run: Run) -> str:
    return run.cast_id if isinstance(run, DamagedRun) else run.hello.cast_id


def run_started(run: Run) -> datetime:
    return run.seen_at if isinstance(run, DamagedRun) else run.hello.started_at


# The tail of a rite's output, not all of it. The journal has the whole stream
# and a surface only ever paints a screenful, so a cast that streams for an hour
# costs the same as one that just started.
# ponytail: fixed tail, per rite. A surface that wants scrollback reads the
# journal, which is where scrollback belongs.
DELTA_LINES = 200


# A view is the message that opened it, plus what has happened since. Copying
# the fields out would be a second place to keep them right — and what a surface
# is replayed is this message again, unchanged.
@dataclass
class RiteView:
    started: RiteStarted
    finished: RiteFinished | None = None
    deltas: deque[str] = field(default_factory=lambda: deque(maxlen=DELTA_LINES))
    # Line for line with `deltas`: whether the line was kept off the terminal.
    quiet: deque[bool] = field(default_factory=lambda: deque(maxlen=DELTA_LINES))

    @property
    def error(self) -> str | None:
        return None if self.finished is None else self.finished.error

    @property
    def finished_at(self) -> datetime | None:
        return None if self.finished is None else self.finished.finished_at


# An open prompt, and the claim id of the surface that took it over if one has.
@dataclass
class Prompt:
    request: DecideRequested
    claim_id: str | None = None


# Insertion-ordered, which is the order the rites began — the tree a surface
# draws is built from each rite's `parent_id` at paint time, so nothing here has
# to hold a second copy of the shape. `waiting` is the open prompts: the daemon
# holds them to say a cast is waiting and to say what for, while answering stays
# the cast's own terminal's job.
@dataclass
class CastView:
    hello: CastHello
    status: CastStatus = "running"
    # The goodbye it ended with, carrying the operator's mark on a failure
    # seen: a surface stops drawing that one loud.
    ended: CastGoodbye | None = None
    rites: dict[str, RiteView] = field(default_factory=dict)
    waiting: dict[str, Prompt] = field(default_factory=dict)
    # The casts it is blocked on, by request: while any is here it holds no
    # process slot.
    on_children: dict[str, AwaitRequested] = field(default_factory=dict)
    # The pooled tree it left unparkable, if it did.
    blocked: TreeBlocked | None = None

    @property
    def detail(self) -> str | None:
        return None if self.ended is None else self.ended.detail

    @property
    def seen(self) -> bool:
        return self.ended is not None and self.ended.seen

    @property
    def failed(self) -> bool:
        return self.status in {"error", "disconnected"}

    # The last time the journal puts on the cast: nothing else in it is dated.
    @property
    def last_seen(self) -> datetime:
        stamps = [self.hello.started_at]
        for rite in self.rites.values():
            stamps += [
                rite.started.started_at,
                *([rite.finished_at] if rite.finished_at else []),
            ]
        return max(stamps)

    # A rite its cast ended inside, without saying how it did, was cancelled.
    def rite_status(self, rite: RiteView) -> RiteStatus:
        if rite.finished is not None:
            return rite.finished.status
        return "running" if self.status in {"running", "queued"} else "cancelled"

    # `CastGoodbye` carries no time, so such a rite's clock stops at the last
    # time the journal dated.
    def rite_finished_at(self, rite: RiteView) -> datetime | None:
        if rite.finished is not None:
            return rite.finished.finished_at
        return None if self.rite_status(rite) == "running" else self.last_seen


# A git common dir is `<repo>/.git` for a checkout and `<repo>.git` bare; the
# repository's name is what an operator calls it either way.
def named(project: str) -> str:
    where = PurePath(project)
    return where.parent.name if where.name == ".git" else where.name


# What a surface reads the daemon for. Ordered, because the number an operator
# types is a position in what they are looking at.
class Casts(Protocol):
    @property
    def casts(self) -> dict[str, CastView]: ...


# What the circle keeps casts in: it reads their views, and writes the records
# of the casts it queues and of those that end before their hello, and answers
# a cast's await down its connection: `False` when it is not connected.
class CastBoard(Casts, Protocol):
    def apply(self, message: CastMessage) -> None: ...
    def tell(self, cast_id: str, message: WireMessage) -> bool: ...
