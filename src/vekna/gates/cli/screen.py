from collections.abc import Sequence
from itertools import starmap

from vekna.pacts.casts import CastView, RiteView
from vekna.wire import RunRecord

_CAST_GLYPH = {"running": "▶", "ok": "✓", "error": "✗", "disconnected": "⚠"}
_RITE_GLYPH = {"running": "▶", "ok": "✓", "error": "✗"}
_WAITING = "⏸"
_MEDIUM = "↳"
_HOME = "\x1b[H\x1b[2J"
_LIST_KEYS = "number to drill in · q to quit"
_CAST_KEYS = "b back · q quit"
_ANSWER_HERE = "answer it where the cast was started"
_DELTA_TAIL = 12


def _project(view: CastView) -> str:
    return (
        view.hello.project_root.rsplit("/", maxsplit=1)[-1] or view.hello.project_root
    )


def _glyph(view: CastView) -> str:
    if view.waiting and view.status == "running":
        return _WAITING
    return _CAST_GLYPH[view.status]


def _summary(view: CastView) -> str:
    if view.waiting:
        first = next(iter(view.waiting.values()))
        return f"waiting: {first.prompt}"
    if view.status == "running":
        return f"{len(view.rites)} rites"
    return view.detail or ""


def _line(index: int, view: CastView) -> str:
    return (
        f" [{index}] {_glyph(view)} {view.hello.ritual:<16}"
        f" {_project(view):<16} {_summary(view)}".rstrip()
    )


def _counted(total: int) -> str:
    return "1 cast" if total == 1 else f"{total} casts"


def _listing(casts: Sequence[CastView]) -> list[str]:
    if not casts:
        return ["", " no casts — run `vekna cast <ritual>` anywhere", ""]
    return ["", *starmap(_line, enumerate(casts, 1)), ""]


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


def _drilled(view: CastView) -> list[str]:
    header = f"vekna — {view.hello.ritual}  {view.hello.project_root}  {view.status}"
    return [header, "", *_rite_lines(view), *_waiting_lines(view), ""]


# `vekna casts` reads the journal rather than the daemon: the daemon writes
# every cast it sees to disk as it sees it, so what is on disk is what it knows,
# and a listing needs no socket at all.
def listing(records: Sequence[RunRecord]) -> str:
    if not records:
        return "no casts recorded\n"
    # In the reader's own time: the record carries UTC, and an operator east of
    # it reading a bare wall clock has no way to tell.
    return "".join(
        f"{record.hello.cast_id[:8]}  {_CAST_GLYPH[record.status]}"
        f"  {record.hello.ritual:<16}"
        f"  {record.hello.started_at.astimezone():%Y-%m-%d %H:%M}"
        f"  {record.hello.project_root}\n"
        for record in records
    )


# One string, painted over the top of the last one. A terminal that can only be
# written to forwards is what the CLI surface has; the Textual dashboard in
# `docs/eye/01-tui.md` is where partial redraws belong.
def paint(*, casts: Sequence[CastView], focus: str | None, note: str = "") -> str:
    found = [view for view in casts if view.hello.cast_id == focus]
    if focus is not None and found:
        body = _drilled(found[0])
        keys = _CAST_KEYS
    else:
        body = [f"vekna — {_counted(len(casts))}", *_listing(casts)]
        keys = _LIST_KEYS
    lines = [*body, f" {note}" if note else "", f" {keys}"]
    return _HOME + "\n".join(lines) + "\n"
