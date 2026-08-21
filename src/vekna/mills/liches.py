import secrets
from collections.abc import Callable, Collection, Sequence
from datetime import UTC, datetime

from vekna.pacts.lich import LichView, Phylactery, Registry, Station
from vekna.pacts.routing import Action, Routed
from vekna.specs.names import ADJECTIVES, NOUNS
from vekna.wire import LichFell, LichRose, LichStatus, LichUpdate, SurfaceCommand

# How many pairs are drawn before the name gets a number on the end. With 256
# pairs and a handful taken, a run this long means the draw is unlucky rather
# than the list exhausted — and counting up from 2 is what a project with three
# hundred liches would want anyway.
_DRAWS = 20
_ALREADY = "a lich of that name is already standing"

Choose = Callable[[Sequence[str]], str]


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _unrouted(_: Routed) -> None:
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
        self, *, registry: Registry, on_routed: Callable[[Routed], None] = _unrouted
    ) -> None:
        self._registry = registry
        self._on_routed = on_routed
        self._live: dict[str, LichView] = {}

    @property
    def live(self) -> dict[str, LichView]:
        return self._live

    # Returns why the rising was refused, or None once it stands. Two processes
    # answering to one name is the one thing that cannot be allowed: the name is
    # the address, and commands would go to whichever the dict last saw.
    def rose(self, message: LichRose, station: Station) -> str | None:
        if message.name in self._live:
            self._say(kind=message.kind, name=message.name, action="dropped")
            return _ALREADY
        self._live[message.name] = LichView(rose=message, station=station)
        self._remember(message)
        self._say(kind=message.kind, name=message.name, action="applied")
        return None

    def apply(self, message: LichUpdate) -> None:
        if (view := self._live.get(message.name)) is None:
            self._say(kind=message.kind, name=message.name, action="dropped")
            return
        if isinstance(message, LichStatus):
            view.said = message
        else:
            del self._live[message.name]
        self._say(kind=message.kind, name=message.name, action="applied")

    # A lich whose socket closed without a word gets a `LichFell` anyway, or the
    # daemon holds a station that commands vanish into.
    def gone(self, name: str) -> None:
        self.apply(LichFell(name=name, reason="disconnected"))

    # A command from a surface, addressed by name. A dismissal reaches a dormant
    # lich too — there is no process to tell, and dropping the row is the whole
    # of what "dismissed" means for one.
    def command(self, message: SurfaceCommand) -> None:
        self._registry.drop(message.name)
        if (view := self._live.get(message.name)) is None:
            self._say(kind=message.kind, name=message.name, action="dropped")
            return
        view.station.send(message)
        self._say(kind=message.kind, name=message.name, action="applied")

    # A rising is not always a new lich: one raised again keeps the row it had,
    # so its channel and the day it was first raised survive the process that
    # died. What it does learn is where it stands now.
    def _remember(self, message: LichRose) -> None:
        found = {row.name: row for row in self._registry.rows()}
        if (row := found.get(message.name)) is None:
            row = Phylactery(name=message.name, root=message.root, created=_now())
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
