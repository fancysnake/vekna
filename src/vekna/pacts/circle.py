from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pydantic import JsonValue

from vekna.wire import AltarRequested, CastHello, TendedTree

# What a project's circle allows when nothing says otherwise.
DEFAULT_PROCESSES = 4
DEFAULT_WORKTREES = 2


# Read each time they are asked for, so an edited config counts from the next
# cast on without restarting the daemon. `processes`, `worktrees`, `prepare`
# and `base` are per project, found from the tree the cast was asked from;
# `coding` and `total` are per machine, so only the user's own config says
# them: `None` is no limit on `coding`, and `total` is how many casts run at
# once across every project. `vigils` is how many of those a vigil may have
# started. `base` is the project's `base_branch`, and `None` is the `HEAD` of
# the tree the altar was asked from.
class Limits(Protocol):
    def processes(self, project_root: str) -> int: ...
    def worktrees(self, project_root: str) -> int: ...
    def prepare(self, project_root: str) -> str | None: ...
    def base(self, project_root: str) -> str | None: ...
    def coding(self) -> int | None: ...
    def total(self) -> int: ...
    def vigils(self) -> int: ...


# A ritual the daemon casts in one project whenever `every` seconds have passed
# since a cast of it last started there. `args` are the ritual's components, as
# flags typed after its name would set them.
@dataclass(frozen=True, kw_only=True)
class Vigil:
    name: str
    project_root: str
    ritual: str
    every: int
    args: Mapping[str, JsonValue]


# What a vigil needs of the daemon's scheduler. `has_spare` is room that no
# queued cast is waiting for, so a cast enqueued on it starts at once.
class CastQueue(Protocol):
    def has_spare(self, *, project_root: str, project: str) -> bool: ...
    def enqueue(self, hello: CastHello) -> None: ...


# Read each time it is asked, so an edited config counts from the next look.
class VigilBook(Protocol):
    def vigils(self) -> list[Vigil]: ...


# How a spawned cast process ended, and the last thing it said: a cast that dies
# before its hello — a ritual that is not there, a component that will not
# validate — has nothing on the wire, so this is all there is to say why.
@dataclass(frozen=True, kw_only=True)
class Exited:
    code: int | None
    said: str


# The tree is where the cast runs, or `None` for the tree it was asked from.
Spawn = Callable[[CastHello, str | None], Awaitable[Exited]]


# A cast process a daemon spawned and was still waiting on when it stopped. The
# next daemon hears from the cast only once it reattaches, so until then this is
# what says the cast holds a slot, and the tree it stands in.
@dataclass(frozen=True, kw_only=True)
class Spawned:
    cast_id: str
    pid: int
    project: str
    tree: str | None


# No tree could be leased: the pool was never set up, or every tree of it is
# blocked. The cast that wanted one ends with this as its reason. Also why the
# altar could not read the pool at all.
class TreeError(Exception):
    pass


# What `vekna altar` asked for, with what the project's config says of its
# pool: `count` trees, each standing on `base` and set up by `prepare`.
@dataclass(frozen=True, kw_only=True)
class Tending:
    asked: AltarRequested
    project: str
    count: int
    base: str | None
    prepare: str | None


# No tree to lease while some are held: `held` is those of the lease's `held`
# that stand in a tree of the pool, never empty.
@dataclass(frozen=True, kw_only=True)
class Full:
    held: frozenset[str]


# A project's pooled worktrees, read off git each time rather than remembered.
# `held` is every tree a live cast stands in, which only the daemon knows.
class Trees(Protocol):
    # A free tree that the altar set up; `Full` while one is held, as it frees
    # when its cast ends. Makes none. Raises `TreeError` when no tree is set
    # up, and when every tree is blocked, since nothing would free one.
    async def lease(
        self, *, project_root: str, project: str, held: set[str]
    ) -> str | Full: ...

    # Why the tree could not be parked, or `None` once it is.
    async def release(self, tree: str) -> str | None: ...

    # What each tree of the pool came to, in the order done: removed, then
    # fixed, then made and set up. A tree in `held` is left alone, and with
    # nothing asked every tree is, and is said as it stands. Asked for one
    # tree, a held one is a failure. Raises `TreeError` when the pool or the
    # base cannot be read, or the pool lacks the tree asked for; a tree that
    # will not come right is said in its own entry.
    async def tend(self, tending: Tending, held: set[str]) -> list[TendedTree]: ...
