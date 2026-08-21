import secrets
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime

from vekna.pacts.lich import LichView, Phylactery, Registry, Station
from vekna.pacts.routing import Action, Routed
from vekna.specs.names import ADJECTIVES, NOUNS
from vekna.wire import (
    LichDismissRequested,
    LichFell,
    LichRose,
    LichStatus,
    LichUpdate,
    SurfaceCommand,
    WireMessage,
)

# How many pairs are drawn before the name gets a number on the end. With 256
# pairs and a handful taken, a run this long means the draw is unlucky rather
# than the list exhausted — and counting up from 2 is what a project with three
# hundred liches would want anyway.
_DRAWS = 20
_ALREADY = "a lich of that name is already standing"

Choose = Callable[[Sequence[str]], str]
# What a lich said, and which lich said it. The daemon's surfaces live with the
# hub, so this is how they are reached from here — `inits` binds the two.
Broadcast = Callable[[WireMessage, str], None]


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _unrouted(_: Routed) -> None:
    pass


def _unheard(_: WireMessage, __: str) -> None:
    pass


# The daemon's half of a lich: which ones it can currently reach, and the rows
# behind them. The row is the lich and the connection is only how to talk to it,
# so this holds both and confuses neither — `live` is what the socket knows,
# `rows` is what survives the process.
# It may not reach for the hub (`inside-mills` independence) and does not need
# to: a cast a lich spawns reports itself like any other, and `inits` is what
# hands one inbound frame to both.
class Liches:
    def __init__(
        self,
        *,
        registry: Registry,
        on_routed: Callable[[Routed], None] = _unrouted,
        on_said: Broadcast = _unheard,
    ) -> None:
        self._registry = registry
        self._on_routed = on_routed
        self._on_said = on_said
        self._live: dict[str, LichView] = {}

    @property
    def live(self) -> dict[str, LichView]:
        return self._live

    # Returns why the rising was refused, or None once it stands. Two processes
    # answering to one name is the one thing that cannot be allowed: the name is
    # the address, and commands would go to whichever the dict last saw.
    def rose(self, message: LichRose, station: Station) -> str | None:
        if message.lich in self._live:
            self._say(kind=message.kind, name=message.lich, action="dropped")
            return _ALREADY
        self._live[message.lich] = LichView(rose=message, station=station)
        self._remember(message)
        self._accept(message)
        return None

    # What a lich says goes out to whoever is watching, the way a cast's events
    # do: a shell attached to the session and a channel are the same thing here.
    def apply(self, message: LichUpdate) -> None:
        if (view := self._live.get(message.lich)) is None:
            self._say(kind=message.kind, name=message.lich, action="dropped")
            return
        if isinstance(message, LichStatus):
            view.said = message
        elif isinstance(message, LichFell):
            del self._live[message.lich]
        # A refusal changes nothing the daemon holds — the lich is still
        # standing, still casting what it was — and is passed straight on.
        self._accept(message)

    def _accept(self, message: LichRose | LichUpdate) -> None:
        self._on_said(message, message.lich)
        self._say(kind=message.kind, name=message.lich, action="applied")

    # A lich whose socket closed without a word gets a `LichFell` anyway, or the
    # daemon holds a station that commands vanish into.
    def gone(self, name: str) -> None:
        self.apply(LichFell(lich=name, reason="disconnected"))

    # A command from a surface, addressed by name. A dismissal reaches a dormant
    # lich too — there is no process to tell, and dropping the row is the whole
    # of what "dismissed" means for one. Everything else needs a process, and
    # for a lich that has none there is nothing to do but say so.
    def command(self, message: SurfaceCommand) -> None:
        if isinstance(message, LichDismissRequested):
            self._registry.drop(message.lich)
        if (view := self._live.get(message.lich)) is None:
            self._say(kind=message.kind, name=message.lich, action="dropped")
            return
        view.station.send(message)
        self._say(kind=message.kind, name=message.lich, action="applied")

    # A cast that says which lich spawned it, which is the only place either the
    # row or the view learns the id: the cast makes it and reports it over its
    # own connection, and the lich that asked for it never sees one.
    def cast_started(self, *, lich: str, cast_id: str) -> None:
        found = {row.name: row for row in self._registry.rows()}
        if (row := found.get(lich)) is not None:
            row.last_cast = cast_id
            self._registry.save(row)
        view = self._live.get(lich)
        # Written out rather than copied-with-changes: `model_copy` comes back
        # as `Any`, and the repository counts every one of those.
        if view is not None and (said := view.said) is not None:
            view.said = LichStatus(
                lich=said.lich, ritual=said.ritual, cast_id=cast_id, since=said.since
            )

    # A rising is not always a new lich: one raised again keeps the row it had,
    # so the day it was first raised — and whatever a later release hangs off
    # the row — survives the process that died. What it learns is where it
    # stands now.
    def _remember(self, message: LichRose) -> None:
        found = {row.name: row for row in self._registry.rows()}
        if (row := found.get(message.lich)) is None:
            row = Phylactery(name=message.lich, root=message.root, created=_now())
        else:
            row.root = message.root
        self._registry.save(row)

    def _say(self, *, kind: str, name: str, action: Action) -> None:
        self._on_routed(Routed(kind=kind, subject=name, action=action))


# Sticky once drawn, so this runs at a lich's first rising and never again. The
# check is against *every* row, live or dormant: the name is the key, and a
# dormant lich answering to the same one is how a revive would reach the wrong
# station.
def draw_name(*, taken: Collection[str], choose: Choose = secrets.choice) -> str:
    for _ in range(_DRAWS):
        if (drawn := f"{choose(ADJECTIVES)}-{choose(NOUNS)}") not in taken:
            return drawn
    return _numbered(f"{choose(ADJECTIVES)}-{choose(NOUNS)}", taken=taken)


# A name nobody holds, from one that somebody does. Bounded by the number of
# rows: `len(taken) + 2` suffixes cannot all be taken by `len(taken)` rows.
def _numbered(base: str, *, taken: Collection[str]) -> str:
    for suffix in range(2, len(taken) + 3):
        if (numbered := f"{base}-{suffix}") not in taken:
            return numbered
    raise AssertionError(base)  # pragma: no cover — more suffixes than rows


# What `vekna lich` offers where it is run, and nothing else. Filtered by root
# because the prompt is fifty entries deep by the second month otherwise, and a
# lich rooted somewhere else is not a thing this directory can carry on.
# Newest first: the one you were working in yesterday is the one you mean today.
def sleeping_here(rows: Sequence[Phylactery], *, root: str) -> list[Phylactery]:
    here = [row for row in rows if row.root == root]
    return sorted(here, key=_raised_at, reverse=True)


# A named function rather than a lambda or an `attrgetter`: both come back as
# `Any` to a type checker reading this at its strictest, and the repository
# counts every one of those.
def _raised_at(row: Phylactery) -> datetime:
    return row.created
