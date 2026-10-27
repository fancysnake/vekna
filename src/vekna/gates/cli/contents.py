from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal, Self

from vekna.pacts.casts import CastView, RiteView

from .cast_text import named

Kind = Literal["project", "ritual", "cast", "more", "rite"]

_LIVE = frozenset({"running", "queued"})
_FAILED = frozenset({"error", "disconnected"})


# What still happens under a node: a fold hides the node's children, and these
# are what it says instead. A cast that asks is counted as asking only, and a
# failure counts until the operator has opened its cast.
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


# Each key opens with what its line is, so the line need not say it twice.
_KINDS: dict[str, Kind] = {
    "p": "project",
    "r": "ritual",
    "c": "cast",
    "…": "more",
    "t": "rite",
}


# One line of the contents. The key is stable across repaints, so the cursor and
# the operator's folds stay on the line they were put on. A folded line keeps
# its children and is drawn without them, so what `w` and `t` reach into a fold
# for is still there.
@dataclass(frozen=True)
class Entry:
    key: str
    name: str
    counts: Counts
    folded: bool = False
    view: CastView | None = None
    rite: RiteView | None = None
    children: tuple["Entry", ...] = ()

    @property
    def kind(self) -> Kind:
        return _KINDS[self.key.split(":", 1)[0]]

    @property
    def happening(self) -> bool:
        counts = self.counts
        return bool(counts.asks or counts.fails or counts.running)

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


# How the contents are read: every cast or only the running ones, the lines
# the operator folded, and the failed casts already opened.
@dataclass(frozen=True)
class _Reading:
    everything: bool
    folded: set[str]
    seen: set[str]


def _named(entry: Entry) -> str:
    return entry.name


def _started(view: CastView) -> datetime:
    return view.hello.started_at


# Project > ritual > cast, newest first > rites. Running only, the contents
# hold the live casts, each as `…` and the one rite that says what it is
# doing now, and the failed ones not yet opened; everything, they hold every
# cast and the whole of each rite tree.
# Every project the casts touch stays, quiet or not, so a failure in it has a
# line to count on.
def contents(
    casts: Sequence[CastView], *, everything: bool, folded: set[str], seen: set[str]
) -> list[Entry]:
    reading = _Reading(everything=everything, folded=folded, seen=seen)
    by_project: dict[str, list[CastView]] = {}
    for view in casts:
        by_project.setdefault(project_key(view), []).append(view)
    projects = [_project(key, views, reading) for key, views in by_project.items()]
    return sorted(projects, key=_named)


def _project(key: str, views: list[CastView], reading: _Reading) -> Entry:
    by_ritual: dict[str, list[CastView]] = {}
    for view in views:
        by_ritual.setdefault(view.hello.ritual, []).append(view)
    rituals = [
        _ritual(ritual_key(ritual_views[0]), ritual_views, reading)
        for _, ritual_views in sorted(by_ritual.items())
    ]
    shown = [entry for entry in rituals if reading.everything or entry.happening]
    return _fold(
        Entry(
            key=key,
            name=named(views[0].hello.project),
            counts=sum((entry.counts for entry in rituals), Counts()),
            children=tuple(shown),
        ),
        reading.folded,
    )


def _ritual(key: str, views: list[CastView], reading: _Reading) -> Entry:
    newest = sorted(views, key=_started, reverse=True)
    kept = [view for view in newest if reading.everything or _happening(view, reading)]
    return _fold(
        Entry(
            key=key,
            name=views[0].hello.ritual,
            counts=sum((_counts(view, reading.seen) for view in views), Counts()),
            children=tuple(_cast(view, reading) for view in kept),
        ),
        reading.folded,
    )


def _cast(view: CastView, reading: _Reading) -> Entry:
    cast_id = view.hello.cast_id
    rites = rite_tree(view) if reading.everything else _now(view)
    return _fold(
        Entry(
            key=cast_key(cast_id),
            name=view.hello.ritual,
            counts=_counts(view, reading.seen),
            view=view,
            children=tuple(rites),
        ),
        reading.folded,
    )


# Still worth a line while running only: live, or a failure not yet opened.
def _happening(view: CastView, reading: _Reading) -> bool:
    return view.status in _LIVE or bool(_counts(view, reading.seen).fails)


def _counts(view: CastView, seen: set[str]) -> Counts:
    if view.waiting:
        return Counts(asks=1)
    if view.status in _LIVE:
        return Counts(running=1)
    unseen = view.status in _FAILED and view.hello.cast_id not in seen
    return Counts(fails=int(unseen))


# The rite that says what the cast is doing: the one that asks, else the
# innermost one still running. The ones before it are `…`, so a cast reads as
# one line of what is happening however many steps it has behind it.
def _now(view: CastView) -> list[Entry]:
    if (rite := _asking(view) or _innermost(view)) is None:
        return []
    entries = [_rite(view, rite, ())]
    if len(view.rites) > 1:
        cast_id = view.hello.cast_id
        entries.insert(
            0, Entry(key=f"…:{cast_id}", name="…", counts=Counts(), view=view)
        )
    return entries


def _asking(view: CastView) -> RiteView | None:
    for prompt in view.waiting.values():
        if (rite := view.rites.get(prompt.request.rite_id or "")) is not None:
            return rite
    return None


def _innermost(view: CastView) -> RiteView | None:
    running = [rite for rite in view.rites.values() if rite.status == "running"]
    return running[-1] if running else None


# Each rite under its parent, in the order they began. One whose parent never
# arrived hangs off the cast rather than going missing, and a chain a peer made
# loop is cut where it would close, so the tree is its own bound.
def rite_tree(view: CastView) -> list[Entry]:
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
        return _rite(view, rite, tuple(under))

    return [grow(rite) for rite in children.get(None, [])]


def _rite(view: CastView, rite: RiteView, under: tuple[Entry, ...]) -> Entry:
    cast_id = view.hello.cast_id
    return Entry(
        key=f"t:{cast_id}:{rite.started.rite_id}",
        name=rite.started.name,
        counts=Counts(),
        view=view,
        rite=rite,
        children=under,
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
