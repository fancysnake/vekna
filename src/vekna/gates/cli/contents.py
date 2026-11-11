from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal, Self

from vekna.pacts.casts import CastView, RiteView

from .cast_text import ended_at, innermost, live, named

Kind = Literal["project", "ritual", "cast", "more", "rite", "day", "history"]

HISTORY_AFTER = timedelta(days=1)

_FAILED = frozenset({"error", "disconnected"})


# What happens under a node: a fold hides the node's children, and these are
# what it says instead. A cast that asks is counted as asking only.
@dataclass(frozen=True)
class Counts:
    asks: int = 0
    fails: int = 0
    running: int = 0

    def __add__(self, other: Self) -> Self:
        return type(self)(
            asks=self.asks + other.asks,
            fails=self.fails + other.fails,
            running=self.running + other.running,
        )


# One line of the contents. The key is stable across repaints, so the cursor and
# the operator's folds stay on the line they were put on. A folded line keeps
# its children and is drawn without them, so what `w` and `t` reach into a fold
# for is still there. A project, ritual or day line holds every cast of its
# own, newest first, and the tree view's `history` line every cast the history
# view has. `said` is what a cast line says in place of how long ago it began.
@dataclass(frozen=True)
class Entry:  # pylint: disable=too-many-instance-attributes
    key: str
    kind: Kind
    name: str
    counts: Counts
    said: str = ""
    folded: bool = False
    view: CastView | None = None
    rite: RiteView | None = None
    views: tuple[CastView, ...] = ()
    children: tuple["Entry", ...] = ()

    @property
    def shown(self) -> tuple["Entry", ...]:
        return () if self.folded else self.children

    # Every cast under the line, folded away or not.
    @property
    def casts(self) -> tuple[str, ...]:
        if self.view is not None:
            return (self.view.hello.cast_id,)
        return tuple(cast for child in self.children for cast in child.casts)


def project_key(view: CastView) -> str:
    return f"p:{view.hello.project}"


def ritual_key(view: CastView) -> str:
    return f"r:{view.hello.project}:{view.hello.ritual}"


def cast_key(cast_id: str) -> str:
    return f"c:{cast_id}"


# How the contents are read: the lines the operator folded, the casts whose
# whole rite tree they opened, the tree view or the history view, and how long
# after it ended a cast moves from the one to the other.
@dataclass
class Reading:
    folded: set[str] = field(default_factory=set)
    whole: set[str] = field(default_factory=set)
    history: bool = False
    history_after: timedelta = HISTORY_AFTER


def _named(entry: Entry) -> str:
    return entry.name


def _started(view: CastView) -> datetime:
    return view.hello.started_at


def _ended(view: CastView) -> datetime:
    return ended_at(view) or view.hello.started_at


# A cast that asks is the operator's business however long ago it ended.
def _historic(view: CastView, reading: Reading, now: datetime) -> bool:
    if live(view) or view.waiting:
        return False
    return now - _ended(view) >= reading.history_after


# The tree view, "how is it going": project > ritual > cast, newest first >
# rites, holding every cast that is live or ended less than `history_after`
# ago, and a last line naming how many the history view has. A cast is one line
# until the operator opens it: a live one also says the rite it is on, after
# `…` for the rites before it. Opened, it holds its whole rite tree.
# The history view, "what happened and when": day > cast, newest first, of the
# casts that ended longer ago than that.
def contents(casts: Sequence[CastView], reading: Reading, now: datetime) -> list[Entry]:
    old = [view for view in casts if _historic(view, reading, now)]
    if reading.history:
        return _days(old, reading)
    by_project: dict[str, list[CastView]] = {}
    for view in casts:
        if view not in old:
            by_project.setdefault(project_key(view), []).append(view)
    projects = [_project(key, views, reading) for key, views in by_project.items()]
    lines = sorted(projects, key=_named)
    if old:
        many = "1 cast" if len(old) == 1 else f"{len(old)} casts"
        lines.append(
            Entry(
                key="history",
                kind="history",
                name=f"history · {many} · H",
                counts=Counts(),
                views=tuple(old),
            )
        )
    return lines


# A day is the reader's own, like every time the window says.
def _days(views: list[CastView], reading: Reading) -> list[Entry]:
    by_day: dict[str, list[CastView]] = {}
    for view in sorted(views, key=_ended, reverse=True):
        day = f"{_ended(view).astimezone():%Y-%m-%d %a}"
        by_day.setdefault(day, []).append(view)
    return [_day(day, found, reading) for day, found in by_day.items()]


def _day(day: str, views: list[CastView], reading: Reading) -> Entry:
    casts = [
        _cast(
            view,
            reading,
            said=f"{_ended(view).astimezone():%H:%M}  {view.hello.ritual}",
        )
        for view in views
    ]
    return _fold(
        Entry(
            key=f"d:{day}",
            kind="day",
            name=day,
            counts=sum((entry.counts for entry in casts), Counts()),
            views=tuple(views),
            children=tuple(casts),
        ),
        reading.folded,
    )


def _project(key: str, views: list[CastView], reading: Reading) -> Entry:
    by_ritual: dict[str, list[CastView]] = {}
    for view in views:
        by_ritual.setdefault(view.hello.ritual, []).append(view)
    rituals = [
        _ritual(ritual_key(ritual_views[0]), ritual_views, reading)
        for _, ritual_views in sorted(by_ritual.items())
    ]
    return _fold(
        Entry(
            key=key,
            kind="project",
            name=named(views[0].hello.project),
            counts=sum((entry.counts for entry in rituals), Counts()),
            views=tuple(sorted(views, key=_started, reverse=True)),
            children=tuple(rituals),
        ),
        reading.folded,
    )


def _ritual(key: str, views: list[CastView], reading: Reading) -> Entry:
    newest = sorted(views, key=_started, reverse=True)
    casts = [_cast(view, reading) for view in newest]
    return _fold(
        Entry(
            key=key,
            kind="ritual",
            name=views[0].hello.ritual,
            counts=sum((entry.counts for entry in casts), Counts()),
            views=tuple(newest),
            children=tuple(casts),
        ),
        reading.folded,
    )


# A cast with nothing to say of now is folded over its whole rite tree until
# it is opened; one that has no rites has nothing to open.
def _cast(view: CastView, reading: Reading, said: str = "") -> Entry:
    cast_id = view.hello.cast_id
    opened = cast_id in reading.whole
    now = [] if opened else _now(view)
    return Entry(
        key=cast_key(cast_id),
        kind="cast",
        name=view.hello.ritual,
        counts=_counts(view),
        said=said,
        folded=not opened and not now and bool(view.rites),
        view=view,
        children=tuple(now or rite_tree(view, reading.folded)),
    )


def _counts(view: CastView) -> Counts:
    if view.waiting:
        return Counts(asks=1)
    if live(view):
        return Counts(running=1)
    return Counts(fails=int(view.status in _FAILED))


# The rite that says what the cast is doing: the one that asks, else the
# innermost one still running. The ones before it are `…`, so a cast reads as
# one line of what is happening however many steps it has behind it.
def _now(view: CastView) -> list[Entry]:
    if (rite := _asking(view) or innermost(view)) is None:
        return []
    entries = [_rite(view, rite, (), set())]
    if len(view.rites) > 1:
        cast_id = view.hello.cast_id
        entries.insert(
            0,
            Entry(
                key=f"…:{cast_id}", kind="more", name="…", counts=Counts(), view=view
            ),
        )
    return entries


def _asking(view: CastView) -> RiteView | None:
    for prompt in view.waiting.values():
        if (rite := view.rites.get(prompt.request.rite_id or "")) is not None:
            return rite
    return None


# Each rite under its parent, in the order they began. One whose parent never
# arrived hangs off the cast rather than going missing, and so does the first
# rite of a loop with no way in; a loop is cut where it would close, so the
# tree is its own bound.
def rite_tree(view: CastView, folded: set[str] | None = None) -> list[Entry]:
    children: dict[str | None, list[RiteView]] = {}
    for rite in view.rites.values():
        parent = rite.started.parent_id
        children.setdefault(parent if parent in view.rites else None, []).append(rite)
    seen: set[str] = set()

    def grow(rite: RiteView) -> Entry:
        seen.add(rite.started.rite_id)
        under = [
            grow(child)
            for child in children.get(rite.started.rite_id, [])
            if child.started.rite_id not in seen
        ]
        return _rite(view, rite, tuple(under), folded or set())

    # Checked one at a time, so a rite an earlier one grew is passed over.
    roots = [*children.get(None, []), *view.rites.values()]
    return [grow(rite) for rite in roots if rite.started.rite_id not in seen]


def _rite(
    view: CastView, rite: RiteView, under: tuple[Entry, ...], folded: set[str]
) -> Entry:
    cast_id = view.hello.cast_id
    return _fold(
        Entry(
            key=f"t:{cast_id}:{rite.started.rite_id}",
            kind="rite",
            name=rite.started.name,
            counts=Counts(),
            view=view,
            rite=rite,
            children=under,
        ),
        folded,
    )


def _fold(entry: Entry, folded: set[str]) -> Entry:
    if entry.key not in folded:
        return entry
    return replace(entry, folded=True)


# Every line in reading order, with the key of the line it hangs under.
def walked(entries: Sequence[Entry]) -> list[tuple[Entry, str | None]]:
    lines: list[tuple[Entry, str | None]] = []

    def walk(entry: Entry, parent: str | None) -> None:
        lines.append((entry, parent))
        for child in entry.shown:
            walk(child, entry.key)

    for entry in entries:
        walk(entry, None)
    return lines
