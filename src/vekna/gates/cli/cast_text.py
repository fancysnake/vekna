from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import PurePath

from vekna.pacts.casts import CastView
from vekna.wire import SHORT_ID, CastHello

_RESUMED = "↳"
_MINUTE = 60
_HOUR = 3600
_DAY = 86400
# The word, not the glyph: the list is read across a row of casts, and "aborted"
# says in one column what ⚠ needs a legend for. Glyphs stay in the rite tree,
# where the tree shape carries the rest of the meaning.
_WORD = {
    "queued": "queued",
    "running": "running",
    "ok": "done",
    "error": "failed",
    "disconnected": "aborted",
}
_TALLY = (
    "running",
    "waiting",
    "on child",
    "recovering",
    "queued",
    "done",
    "failed",
    "aborted",
)


# A git common dir is `<repo>/.git` for a checkout and `<repo>.git` bare; the
# repository's name is what an operator calls it either way.
def named(project: str) -> str:
    where = PurePath(project)
    return where.parent.name if where.name == ".git" else where.name


def word(view: CastView) -> str:
    if view.status == "running":
        if view.waiting:
            return "waiting"
        if view.on_children:
            return "on child"
        if _recovering(view):
            return "recovering"
    return _WORD[view.status]


# Still running though its last finished step raised: a step took the failure
# and the cast went on. Not a status of its own on the wire — the rites already
# say it.
def _recovering(view: CastView) -> bool:
    finished = [
        rite
        for rite in view.rites.values()
        if rite.started.category == "step" and rite.status != "running"
    ]
    return bool(finished) and finished[-1].status == "error"


# Which cast of a ritual this is, by when it began: a live one is happening now
# whenever it began, and one that ended is placed by how long ago that was.
def ago(view: CastView, now: datetime) -> str:
    seconds = (now - view.hello.started_at).total_seconds()
    if view.status in {"running", "queued"} or seconds < _MINUTE:
        return "@now"
    if seconds < _HOUR:
        return f"@{int(seconds // _MINUTE)}m ago"
    if seconds < _DAY:
        return f"@{int(seconds // _HOUR)}h ago"
    return f"@{int(seconds // _DAY)}d ago"


def clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    if whole < _MINUTE:
        return f"{whole}s"
    if whole < _HOUR:
        return f"{whole // _MINUTE}m{whole % _MINUTE:02d}s"
    return f"{whole // _HOUR}h{whole % _HOUR // _MINUTE:02d}m"


# A cast that has ended stops counting, and `CastGoodbye` carries no time of its
# own: the last rite to finish is when it ended, to within the moment it took to
# say so. Derived rather than stamped on arrival, because a peer surface is
# replayed a cast that ended before it attached and would stamp its own clock.
def _ended_at(view: CastView) -> datetime | None:
    stamps = [rite.finished_at for rite in view.rites.values() if rite.finished_at]
    return max(stamps) if stamps else None


def elapsed(view: CastView, now: datetime) -> str:
    live = view.status in {"running", "queued"}
    if (until := now if live else _ended_at(view)) is None:
        return "—"
    return clock((until - view.hello.started_at).total_seconds())


def counted(casts: Sequence[CastView]) -> str:
    tally = Counter(word(view) for view in casts)
    return " · ".join(f"{tally[word]} {word}" for word in _TALLY if tally[word])


def labelled(hello: CastHello) -> str:
    return f"{hello.ritual} {hello.cast_id[:SHORT_ID]}"


# A resumed cast is a cast of its own with an id of its own, so what would
# otherwise read as the same ritual run twice says which cast it carries on
# from — cut to eight, the form `vekna cast --continue` takes.
def carried(hello: CastHello) -> str:
    said = (
        ""
        if hello.resumed_from is None
        else f"  {_RESUMED} {hello.resumed_from[:SHORT_ID]}"
    )
    if hello.enqueued_by is not None:
        said += f"  queued by {hello.enqueued_by[:SHORT_ID]}"
    return said
