from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from vekna.wire import CastHello, DecideRequested, RiteStarted

# The wire's three final statuses, plus the one a cast has while it is still
# going. Deliberately the same words `CastGoodbye` carries, so nothing has to
# translate between the message and the view it lands in.
CastStatus = Literal["running", "ok", "error", "disconnected"]
RiteStatus = Literal["running", "ok", "error"]

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
    status: RiteStatus = "running"
    finished_at: datetime | None = None
    deltas: deque[str] = field(default_factory=lambda: deque(maxlen=DELTA_LINES))


# Insertion-ordered, which is the order the rites began — the tree a surface
# draws is built from each rite's `parent_id` at paint time, so nothing here has
# to hold a second copy of the shape. `waiting` is the open prompts: the daemon
# holds them to say a cast is waiting and to say what for, while answering stays
# the cast's own terminal's job (docs/reborn/06-vekna-daemon.md).
@dataclass
class CastView:
    hello: CastHello
    status: CastStatus = "running"
    detail: str | None = None
    rites: dict[str, RiteView] = field(default_factory=dict)
    waiting: dict[str, DecideRequested] = field(default_factory=dict)


# `run.json`: what a cast was and how it ended, beside the event log that says
# what it did. The same three fields the view carries, minus everything the log
# can be read for — this is the index, not a second copy.
class RunRecord(BaseModel):
    hello: CastHello
    status: CastStatus = "running"
    detail: str | None = None
