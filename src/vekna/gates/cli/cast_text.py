import re
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from vekna.pacts.casts import CastView, Prompt, RiteView
from vekna.wire import SHORT_ID, CastHello, CastStatus

_RESUMED = "↳"
_MINUTE = 60
_HOUR = 3600
_DAY = 86400
_SLOTS = (1, 3, 6, 12)
# The word, not the glyph: the list is read across a row of casts, and "aborted"
# says in one column what ⚠ needs a legend for. Glyphs stay in the rite tree,
# where the tree shape carries the rest of the meaning.
Word = Literal[
    "queued",
    "running",
    "waiting",
    "on child",
    "recovering",
    "done",
    "failed",
    "aborted",
]
_WORD: dict[CastStatus, Word] = {
    "queued": "queued",
    "running": "running",
    "ok": "done",
    "error": "failed",
    "disconnected": "aborted",
}
# What `word` says of a live cast. An ended one with a prompt open is "waiting" too.
LIVE: tuple[Word, ...] = ("running", "waiting", "on child", "recovering", "queued")
_TALLY: tuple[Word, ...] = (*LIVE, "done", "failed", "aborted")


def live(view: CastView) -> bool:
    return view.status in {"running", "queued"}


# The question on top: the oldest open prompt of a cast. What the operator is
# shown and what an answer goes to are this one.
def top_prompt(view: CastView) -> Prompt | None:
    return next(iter(view.waiting.values()), None)


# What a cast is inside of now: the last rite to begin of those still running,
# of one category or of any.
def innermost(view: CastView, category: str | None = None) -> RiteView | None:
    running = [
        rite
        for rite in view.rites.values()
        if view.rite_status(rite) == "running"
        and category in {None, rite.started.category}
    ]
    return running[-1] if running else None


# A terminal obeys the control characters a ritual or an agent wrote: one cursor
# move draws text outside its pane. A whole escape sequence goes, and a control
# character left alone is shown as `�`.
_ESCAPE = re.compile(
    r"""
    \x1b (?:
        \[ [0-?]* [\x20-/]* [@-~]       # CSI: parameters, intermediates, final byte
      | \] [^\x07\x1b]* (?:\x07|\x1b\\)?  # OSC: to BEL or ST, or to the line's end
      | [\x20-/]* [0-~]                 # nF, Fp, Fe, Fs: intermediates, final byte
    )
    """,
    re.VERBOSE,
)
# Not \x09-\x0d: tab is text, and the rest are line breaks that `splitlines`
# cuts at before any line reaches here.
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f]")


# Text a ritual wrote with nothing in it a terminal would act on, cleaned line by
# line so an unterminated sequence cannot swallow the lines after it.
def printable(text: str) -> str:
    return "\n".join(
        _CONTROL.sub("�", _ESCAPE.sub("", line)) for line in text.splitlines()
    )


# What a rite's call was given, as it follows the rite's name on a line.
def given(rite: RiteView) -> str:
    summary = rite.started.summary
    return f"  {printable(summary)}" if summary else ""


# Text a ritual wrote, to its first line, cut with `…` where it runs past `width`.
def clipped(text: str, width: int) -> str:
    line = next(iter(text.splitlines()), "")
    return f"{line[: width - 1]}…" if len(line) > width else line


# A cast that ended with a prompt still open waits all the same.
def word(view: CastView) -> Word:
    if view.waiting:
        return "waiting"
    if view.status == "running":
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
        if rite.started.category == "step" and view.rite_status(rite) != "running"
    ]
    return bool(finished) and view.rite_status(finished[-1]) == "error"


# When a cast began, as its line says it: a live one is happening now whenever
# it began, and one that ended says the clock time, which under a day names one
# moment and past it needs the date.
def began(view: CastView, now: datetime) -> str:
    seconds = (now - view.hello.started_at).total_seconds()
    if live(view) or seconds < _MINUTE:
        return "@now"
    at = view.hello.started_at.astimezone()
    return f"{at:%H:%M}" if seconds < _DAY else f"{at:%b %d %H:%M}"


# The slot a cast began in, the hours it is younger than: where a streak of
# casts is cut, so one line never stands for casts hours apart.
def ago(view: CastView, now: datetime) -> str:
    seconds = (now - view.hello.started_at).total_seconds()
    if live(view) or seconds < _MINUTE:
        return "@now"
    for hours in _SLOTS:
        if seconds < hours * _HOUR:
            return f"@<{hours}h"
    if seconds < _DAY:
        return "@<1d"
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
def ended_at(view: CastView) -> datetime | None:
    stamps = [rite.finished_at for rite in view.rites.values() if rite.finished_at]
    return max(stamps) if stamps else None


def ended(view: CastView) -> datetime:
    return ended_at(view) or view.hello.started_at


def elapsed(view: CastView, now: datetime) -> str:
    if (until := now if live(view) else ended_at(view)) is None:
        return "—"
    return clock((until - view.hello.started_at).total_seconds())


# How many casts are in each state, in the one order every line says them in.
def tallied(states: Counter[Word]) -> list[tuple[int, Word]]:
    return [(states[said], said) for said in _TALLY if states[said]]


def counted(casts: Sequence[CastView]) -> str:
    states = Counter(word(view) for view in casts)
    return " · ".join(f"{count} {said}" for count, said in tallied(states))


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
    if hello.vigil is not None:
        said += f"  vigil {hello.vigil}"
    return said
