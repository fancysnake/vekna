from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Literal, Self

from vekna.pacts.casts import CastView, RiteView

from .cast_text import ended, innermost, live, named
from .streaks import Kids, kids_of, said_args, streaks, with_kids

Kind = Literal["project", "ritual", "cast", "more", "rite", "day", "finished"]

_HOLDS_CASTS: frozenset[Kind] = frozenset({"project", "ritual", "finished", "day"})


# What happens under a node: a fold hides the node's children, and these are
# what it says instead. A cast that asks is counted as asking only, and a
# failed one marked seen is not counted.
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
# for is still there; a folded cast still draws the casts it queued. A
# project, ritual, `finished` or day line holds every cast under it, newest
# first, the casts others queued too. A cast line holds its streak, newest
# first: the casts before it that ended as it did, which it stands for. It has
# no name: its arguments are on the right page, where there is room for them.
# A `nested` cast hangs under the cast that queued it.
@dataclass(frozen=True)
class Entry:  # pylint: disable=too-many-instance-attributes
    key: str
    kind: Kind
    name: str
    counts: Counts
    folded: bool = False
    view: CastView | None = None
    rite: RiteView | None = None
    views: tuple[CastView, ...] = ()
    streak: tuple[CastView, ...] = ()
    children: tuple["Entry", ...] = ()
    nested: bool = False

    # A folded cast hides its rites, not the casts it queued.
    @property
    def shown(self) -> tuple["Entry", ...]:
        if not self.folded:
            return self.children
        return tuple(child for child in self.children if child.nested)

    # Every cast under the line, folded away or not.
    @property
    def casts(self) -> tuple[str, ...]:
        own = () if self.view is None else (self.view.hello.cast_id,)
        # A rite line is its cast's, so only a cast or a group adds to it.
        return own + tuple(
            cast
            for child in self.children
            if child.kind == "cast" or child.kind in _HOLDS_CASTS
            for cast in child.casts
        )

    # What happens on a cast's line and under it, the casts it queued included.
    @property
    def total(self) -> Counts:
        kids = (child.total for child in self.children if child.kind == "cast")
        return sum(kids, self.counts)


def project_key(view: CastView) -> str:
    return f"p:{view.hello.project}"


def ritual_key(view: CastView) -> str:
    return f"r:{view.hello.project}:{view.hello.ritual}"


def cast_key(cast_id: str) -> str:
    return f"c:{cast_id}"


# The line holding the streaks that ended under a ritual or a project.
def finished_key(under: str) -> str:
    return f"f:{under}"


# How the contents are read: the lines the operator toggled away from how they
# start — a cast starts closed to one line, every other line starts open — the
# tree view or the history view, how long after it ended a cast moves from the
# one to the other, and the cast kept open whatever was toggled: it shows its
# rite tree, and every line it hangs under shows it.
@dataclass
class Reading:
    history_after: timedelta
    toggled: set[str] = field(default_factory=set)
    history: bool = False
    kept_open: str | None = None


def _named(entry: Entry) -> str:
    return entry.name


def _started(view: CastView) -> datetime:
    return view.hello.started_at


def _newest_started(streak: tuple[CastView, ...]) -> datetime:
    return streak[0].hello.started_at


# What the tree view is drawn from besides the reading: the casts each cast
# queued that it draws, and the ids of those; and `ended_by`, every cast each
# cast queued, those in the history view too, since how a cast ended takes in
# all of them.
@dataclass(frozen=True)
class _Tree:
    reading: Reading
    now: datetime
    kids: Kids
    nested: AbstractSet[str]
    ended_by: Kids


def _tree(
    reading: Reading,
    *,
    recent: Sequence[CastView],
    every: Sequence[CastView],
    now: datetime,
) -> _Tree:
    kids = kids_of(recent)
    nested = {kid.hello.cast_id for queued in kids.values() for kid in queued}
    return _Tree(
        reading=reading, now=now, kids=kids, nested=nested, ended_by=kids_of(every)
    )


# A cast that asks is the operator's business however long ago it ended.
def historic(view: CastView, reading: Reading, now: datetime) -> bool:
    if live(view) or view.waiting:
        return False
    return now - ended(view) >= reading.history_after


# The tree view, "how is it going": project > ritual > cast, newest first >
# rites, holding every cast that is live or ended less than `history_after`
# ago. A cast is one line until the operator opens it: a live one also says the
# rite it is on, after `…` for the rites before it. Opened, it holds its whole
# rite tree. A cast that ended like the one before it, of the same ritual and
# arguments, is not drawn: the newest of such a streak stands for all of them.
# A ritual line holds what still runs or asks. Every streak that ended is under
# the project's `finished`, by ritual, newest first. A cast another cast queued
# hangs under that cast.
# The history view, "what happened and when": day > cast, newest first, of the
# casts that ended longer ago than that.
def contents(casts: Sequence[CastView], reading: Reading, now: datetime) -> list[Entry]:
    recent: list[CastView] = []
    old: list[CastView] = []
    for view in casts:
        (old if historic(view, reading, now) else recent).append(view)
    tree = _tree(reading, recent=recent, every=casts, now=now)
    if reading.history:
        return _days(old, tree)
    by_project: dict[str, list[CastView]] = {}
    for view in recent:
        by_project.setdefault(project_key(view), []).append(view)
    projects = [_project(key, views, tree) for key, views in by_project.items()]
    return sorted(projects, key=_named)


# A day is the reader's own, like every time the window says.
def _days(views: list[CastView], tree: _Tree) -> list[Entry]:
    by_day: dict[str, list[CastView]] = {}
    for view in sorted(views, key=ended, reverse=True):
        day = f"{ended(view).astimezone():%Y-%m-%d %a}"
        by_day.setdefault(day, []).append(view)
    return [_day(day, found, tree) for day, found in by_day.items()]


def _day(day: str, views: list[CastView], tree: _Tree) -> Entry:
    casts = [_cast(view=view, tree=tree) for view in views]
    return _fold(
        Entry(
            key=f"d:{day}",
            kind="day",
            name=day,
            counts=sum((entry.counts for entry in casts), Counts()),
            views=tuple(views),
            children=tuple(casts),
        ),
        tree.reading.toggled,
    )


# A line a cast kept open hangs under is never folded.
def _folds(reading: Reading, views: Sequence[CastView]) -> AbstractSet[str]:
    if any(view.hello.cast_id == reading.kept_open for view in views):
        return frozenset()
    return reading.toggled


def _project(key: str, views: list[CastView], tree: _Tree) -> Entry:
    by_ritual: dict[str, list[CastView]] = {}
    for view in views:
        if view.hello.cast_id not in tree.nested:
            by_ritual.setdefault(view.hello.ritual, []).append(view)
    going: list[Entry] = []
    past: list[Entry] = []
    for _, ritual_views in sorted(by_ritual.items()):
        now, before = _streak_lines(ritual_views, tree)
        ritual = ritual_key(ritual_views[0])
        if now:
            going.append(_ritual(key=ritual, lines=now, tree=tree))
        if before:
            past.append(_ritual(key=finished_key(ritual), lines=before, tree=tree))
    lines = [
        *going,
        *([_finished(key=finished_key(key), rituals=past, tree=tree)] if past else []),
    ]
    return _fold(
        Entry(
            key=key,
            kind="project",
            name=named(views[0].hello.project),
            counts=sum((entry.counts for entry in lines), Counts()),
            views=tuple(sorted(views, key=_started, reverse=True)),
            children=tuple(lines),
        ),
        _folds(tree.reading, views),
    )


def _finished(*, key: str, rituals: list[Entry], tree: _Tree) -> Entry:
    views = [view for ritual in rituals for view in ritual.views]
    return _fold(
        Entry(
            key=key,
            kind="finished",
            name="finished",
            counts=sum((entry.counts for entry in rituals), Counts()),
            views=tuple(sorted(views, key=_started, reverse=True)),
            children=tuple(rituals),
        ),
        tree.reading.toggled,
    )


# `lines` are cast lines of one ritual, newest first, each with its streak.
def _ritual(*, key: str, lines: list[Entry], tree: _Tree) -> Entry:
    standing = [view for entry in lines for view in entry.streak]
    views = with_kids(standing, tree.kids)
    return _fold(
        Entry(
            key=key,
            kind="ritual",
            name=standing[0].hello.ritual,
            counts=sum((entry.total for entry in lines), Counts()),
            views=tuple(sorted(views, key=_started, reverse=True)),
            children=tuple(lines),
        ),
        _folds(tree.reading, views),
    )


# The streaks of one ritual as cast lines, newest first: those with anything
# under them that still runs or asks, then those that ended.
def _streak_lines(
    views: list[CastView], tree: _Tree
) -> tuple[list[Entry], list[Entry]]:
    by_args: dict[str, list[CastView]] = {}
    for view in views:
        by_args.setdefault(said_args(view), []).append(view)

    found = [
        streak
        for same in by_args.values()
        for streak in streaks(same, tree.ended_by, now=tree.now)
    ]
    going: list[Entry] = []
    past: list[Entry] = []
    for streak in sorted(found, key=_newest_started, reverse=True):
        first = streak[0]
        entry = _cast(view=first, tree=tree, streak=streak)
        (going if entry.total.asks or entry.total.running else past).append(entry)
    return going, past


# A cast with nothing to say of now is folded over its whole rite tree until
# it is opened; one that has no rites has nothing to open. The casts it queued
# show under it either way.
def _cast(
    *,
    view: CastView,
    tree: _Tree,
    streak: tuple[CastView, ...] = (),
    nested: bool = False,
) -> Entry:
    reading = tree.reading
    cast_id = view.hello.cast_id
    opened = cast_key(cast_id) in reading.toggled or cast_id == reading.kept_open
    now = [] if opened else _now(view)
    return Entry(
        key=cast_key(cast_id),
        kind="cast",
        name="",
        counts=sum(
            (_counts(stood) for stood in _stood_for(view, streak, tree)), Counts()
        ),
        folded=not opened and not now and bool(view.rites),
        view=view,
        streak=streak or (view,),
        children=(*(now or rite_tree(view, reading.toggled)), *_queued(view, tree)),
        nested=nested,
    )


# The casts a line counts itself: the newest cast, whose queued casts are drawn
# under it and counted there, and the casts it stands for with all they queued.
def _stood_for(
    view: CastView, streak: tuple[CastView, ...], tree: _Tree
) -> list[CastView]:
    return [view, *with_kids(streak[1:], tree.kids)]


def _queued(view: CastView, tree: _Tree) -> list[Entry]:
    return [
        _cast(view=kid, tree=tree, nested=True)
        for kid in tree.kids.get(view.hello.cast_id, ())
    ]


def _counts(view: CastView) -> Counts:
    if view.waiting:
        return Counts(asks=1)
    if live(view):
        return Counts(running=1)
    return Counts(fails=int(view.failed and not view.seen))


# The rite that says what the cast is doing: the one that asks, else the
# innermost one still running. The ones before it are `…`, so a cast reads as
# one line of what is happening however many steps it has behind it.
def _now(view: CastView) -> list[Entry]:
    if (rite := _asking(view) or innermost(view)) is None:
        return []
    entries = [_rite(view, rite, (), frozenset())]
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
def rite_tree(view: CastView, folded: AbstractSet[str] = frozenset()) -> list[Entry]:
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
        return _rite(view, rite, tuple(under), folded)

    # Checked one at a time, so a rite an earlier one grew is passed over.
    roots = [*children.get(None, []), *view.rites.values()]
    return [grow(rite) for rite in roots if rite.started.rite_id not in seen]


def _rite(
    view: CastView, rite: RiteView, under: tuple[Entry, ...], folded: AbstractSet[str]
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


def _fold(entry: Entry, folded: AbstractSet[str]) -> Entry:
    if entry.key not in folded:
        return entry
    return replace(entry, folded=True)


# The lines a window opens with toggled, for a tree of at most `rows` lines:
# the most of these that fits. Every running cast open to its whole rite tree;
# then `finished` folded too; then the running casts back to one line; then
# every project where nothing runs folded as well; then every project folded,
# which is taken when nothing fits.
def fitted(
    *, casts: Sequence[CastView], reading: Reading, now: datetime, rows: int
) -> set[str]:
    def lines_with(toggled: set[str]) -> list[Entry]:
        return _lines(casts=casts, reading=replace(reading, toggled=toggled), now=now)

    lines = lines_with(set())
    running = {
        entry.key
        for entry in lines
        if entry.kind == "cast" and entry.view is not None and live(entry.view)
    }
    finished = {entry.key for entry in lines if entry.kind == "finished"}
    projects = {entry.key for entry in lines if entry.kind == "project"}
    idle = {
        entry.key
        for entry in lines
        if entry.kind == "project" and not (entry.counts.asks or entry.counts.running)
    }
    tried = (running, running | finished, finished, finished | idle, projects)
    return next((folds for folds in tried if len(lines_with(folds)) <= rows), tried[-1])


# The lines `f` leaves toggled: every line that holds casts, folded; when they
# all are, none, so every line is back to how it starts.
def folded_all(
    *, casts: Sequence[CastView], reading: Reading, now: datetime
) -> set[str]:
    lines = _lines(casts=casts, reading=replace(reading, toggled=set()), now=now)
    folds = {entry.key for entry in lines if entry.kind in _HOLDS_CASTS}
    return set() if folds <= reading.toggled else folds


def _lines(
    *, casts: Sequence[CastView], reading: Reading, now: datetime
) -> list[Entry]:
    return [entry for entry, _ in walked(contents(casts, reading, now))]


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
