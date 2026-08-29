from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime

from vekna.pacts.casts import CastView, RiteView
from vekna.wire import CastHello, RunRecord

_CAST_GLYPH = {"running": "▶", "ok": "✓", "error": "✗", "disconnected": "⚠"}
_RITE_GLYPH = {"running": "▶", "ok": "✓", "error": "✗"}
_WAITING = "⏸"
_MEDIUM = "↳"
_GAP = "◌"
_HOME = "\x1b[H\x1b[2J"
_LIST_KEYS = "number to drill in · q to quit"
_CAST_KEYS = "b back · q quit"
_ANSWER_HERE = "answer it where the cast was started"
_DELTA_TAIL = 12
# A daemon left up holds every cast it has ever heard, and what an operator
# came to look at is the ones still going. Every running cast shows whatever
# else is on screen; the finished ones fill what is left, and `vekna log` has
# the rest.
_SHOWN = 12
# The word, not the glyph: the list is read across a row of casts, and "aborted"
# says in one column what ⚠ needs a legend for. Glyphs stay in the rite tree,
# where the tree shape carries the rest of the meaning.
_WORD = {
    "running": "running",
    "ok": "done",
    "error": "failed",
    "disconnected": "aborted",
}
_TALLY = ("running", "waiting", "done", "failed", "aborted")
_ID = 8
_RITUAL = 15
_PROJECT = 10
_NOW = 44
_HEAD = (
    f"  #  {'cast':<{_ID}}  {'ritual':<{_RITUAL}}  {'project':<{_PROJECT}}"
    f"  {'status':<7}  {'elapsed':>7}  steps  now"
)
_MINUTE = 60
_HOUR = 3600


# Whoever is blocked on a human first, then what is still going, then the ones
# that ended, newest first: a cast that ended an hour ago is not what the view
# is for, and one sitting on a question is the whole reason to look at it.
# Shared with the dashboard rather than done at paint time, because the number
# an operator types is a position in this order.
def ordered(casts: Sequence[CastView]) -> list[CastView]:
    live = [view for view in casts if view.status == "running"]
    done = [view for view in casts if view.status != "running"]
    asking = [view for view in live if view.waiting]
    working = [view for view in live if not view.waiting]
    return [*asking, *working, *reversed(done)]


def _project(view: CastView) -> str:
    return (
        view.hello.project_root.rsplit("/", maxsplit=1)[-1] or view.hello.project_root
    )


def _word(view: CastView) -> str:
    if view.waiting and view.status == "running":
        return "waiting"
    return _WORD[view.status]


# Text a ritual wrote reaches a column — a prompt, a step's name — so every one
# of them is cut to its width. Left whole, one long name pushes the columns of
# its own row sideways and the listing stops being a table.
def _fit(text: str, width: int) -> str:
    line = next(iter(text.splitlines()), "")
    return (f"{line[: width - 1]}…" if len(line) > width else line).ljust(width)


def _clock(seconds: float) -> str:
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
    stamps = [
        rite.finished_at for rite in view.rites.values() if rite.finished_at is not None
    ]
    return max(stamps) if stamps else None


def _elapsed(view: CastView, now: datetime) -> str:
    if (until := now if view.status == "running" else _ended_at(view)) is None:
        return "—"
    return _clock((until - view.hello.started_at).total_seconds())


def _steps_done(view: CastView) -> int:
    return sum(
        1
        for rite in view.rites.values()
        if rite.started.category == "step" and rite.status != "running"
    )


def _innermost(view: CastView, category: str) -> RiteView | None:
    found = [
        rite
        for rite in view.rites.values()
        if rite.status == "running" and rite.started.category == category
    ]
    return found[-1] if found else None


# The one free column, and what it says depends on what the cast needs from the
# operator. A waiting cast needs an answer, so it shows the question; an aborted
# one needs restarting, so it shows the command that does it; a running one is
# read to see whether it is stuck, so it shows the step, what the step is doing,
# and how long that has been true. A cast that ended cleanly needs nothing.
def _now(view: CastView, now: datetime) -> str:
    if view.waiting:
        return next(iter(view.waiting.values())).prompt
    if view.status == "disconnected":
        return f"vekna cast --continue {view.hello.cast_id[:_ID]}"
    if (step := _innermost(view, "step")) is None:
        return ""
    medium = _innermost(view, "medium")
    doing = (
        f"{step.started.name} · {medium.started.name}" if medium else step.started.name
    )
    return f"{doing}  {_clock((now - step.started.started_at).total_seconds())}"


def _line(index: int, view: CastView, now: datetime) -> str:
    return (
        f" {index:>2}  {view.hello.cast_id[:_ID]:<{_ID}}"
        f"  {_fit(view.hello.ritual, _RITUAL)}  {_fit(_project(view), _PROJECT)}"
        f"  {_word(view):<7}  {_elapsed(view, now):>7}"
        f"  {_steps_done(view):>5}  {_fit(_now(view, now), _NOW)}".rstrip()
    )


def _counted(casts: Sequence[CastView]) -> str:
    tally = Counter(_word(view) for view in casts)
    return " · ".join(f"{tally[word]} {word}" for word in _TALLY if tally[word])


# Every running cast is on screen whatever else is: they are what the view is
# for, and a machine running fifteen at once is exactly when it matters. What is
# left of the screenful goes to the ones that ended, newest first.
def _shown(casts: Sequence[CastView]) -> Sequence[CastView]:
    live = sum(1 for view in casts if view.status == "running")
    return casts[: max(live, _SHOWN)]


def _listing(casts: Sequence[CastView], now: datetime) -> list[str]:
    if not casts:
        return ["", " no casts — run `vekna cast <ritual>` anywhere", ""]
    shown = _shown(casts)
    lines = [_line(index, view, now) for index, view in enumerate(shown, 1)]
    if (hidden := len(casts) - len(shown)) > 0:
        lines.append(f" … {hidden} older — `vekna log` has them all")
    return ["", _HEAD, *lines, ""]


# Depth by walking parents rather than by remembering one: a rite's place in the
# tree is its parent chain, and the daemon is handed the rites in the order they
# began, not in the shape they make.
# The chain is what a peer said it was, and nothing on the way in checks it for
# loops. Walked recursively, a rite that is its own ancestor painted until the
# recursion limit and took the painting task with it; walked over the rites
# themselves, the tree is its own bound — no chain through it is longer than the
# number of rites in it.
def _depth(rite: RiteView, view: CastView) -> int:
    depth = 0
    parent = rite.started.parent_id
    for _ in view.rites:
        if parent is None or (found := view.rites.get(parent)) is None:
            break
        depth += 1
        parent = found.started.parent_id
    return depth


def _rite_lines(view: CastView) -> list[str]:
    lines: list[str] = []
    for rite in view.rites.values():
        pad = "  " * _depth(rite, view)
        mark = (
            _MEDIUM if rite.started.category == "medium" else _RITE_GLYPH[rite.status]
        )
        lines.append(f" {pad}{mark} {rite.started.name}")
        if rite.status == "running":
            lines += [f" {pad}    {line}" for line in list(rite.deltas)[-_DELTA_TAIL:]]
    return lines


# A resumed cast is a cast of its own with an id of its own, so what would
# otherwise read as the same ritual run twice says which cast it carries on
# from — cut to eight, the form `vekna cast --continue` takes.
def _carried(hello: CastHello) -> str:
    if hello.resumed_from is None:
        return ""
    return f"  {_MEDIUM} {hello.resumed_from[:_ID]}"


def _waiting_lines(view: CastView) -> list[str]:
    if not view.waiting:
        return []
    return [
        "",
        *(
            f" {_WAITING} {request.prompt}   ({_ANSWER_HERE})"
            for request in view.waiting.values()
        ),
    ]


# Why a cast ended the way it did is here and not in the listing: a failure's
# text is a whole traceback's worth in one string, and the listing is a table
# read across ten casts at once.
def _detail_lines(view: CastView) -> list[str]:
    if not view.detail:
        return []
    return ["", *(f" {line}" for line in view.detail.splitlines())]


def _drilled(view: CastView, now: datetime) -> list[str]:
    header = (
        f"vekna — {view.hello.ritual}  {view.hello.project_root}"
        f"  {_word(view)}  {_elapsed(view, now)}  {view.hello.cast_id[:_ID]}"
        f"{_carried(view.hello)}"
    )
    return [
        header,
        "",
        *_rite_lines(view),
        *_waiting_lines(view),
        *_detail_lines(view),
        "",
    ]


# `vekna log` reads the journal rather than the daemon: the daemon writes
# every cast it sees to disk as it sees it, so what is on disk is what it knows,
# and a listing needs no socket at all.
def listing(records: Sequence[RunRecord]) -> str:
    if not records:
        return "no casts recorded\n"
    # In the reader's own time: the record carries UTC, and an operator east of
    # it reading a bare wall clock has no way to tell.
    return "".join(
        f"{record.hello.cast_id[:_ID]}  {_CAST_GLYPH[record.status]}"
        f"  {record.hello.ritual:<16}"
        f"  {record.hello.started_at.astimezone():%Y-%m-%d %H:%M}"
        f"  {record.hello.project_root}{_carried(record.hello)}{_lost(record)}\n"
        for record in records
    )


# A run the daemon could not write part of is still a run, and still resumable
# — it picks up at the last rite that landed. What it is not is complete, and
# the log is the only place an operator finds that out.
def _lost(record: RunRecord) -> str:
    return f"  {_GAP} gap" if record.gapped else ""


# One string, painted over the top of the last one. A terminal that can only be
# written to forwards is what the CLI surface has; the Textual dashboard in
# `docs/eye/tui.md` is where partial redraws belong.
def paint(
    *,
    casts: Sequence[CastView],
    focus: str | None,
    note: str = "",
    now: datetime | None = None,
) -> str:
    at = now if now is not None else datetime.now(UTC)
    found = [view for view in casts if view.hello.cast_id == focus]
    if focus is not None and found:
        body = _drilled(found[0], at)
        keys = _CAST_KEYS
    else:
        ranked = ordered(casts)
        body = [f"vekna — {_counted(ranked)}", *_listing(ranked, at)]
        keys = _LIST_KEYS
    lines = [*body, f" {note}" if note else "", f" {keys}"]
    return _HOME + "\n".join(lines) + "\n"
