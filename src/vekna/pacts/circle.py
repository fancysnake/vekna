from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from vekna.wire import CastHello

# What a project's circle allows when nothing says otherwise.
DEFAULT_PROCESSES = 4
DEFAULT_WORKTREES = 2


# Read each time they are asked for, so an edited config counts from the next
# cast on without restarting the daemon. `processes`, `worktrees` and `prepare`
# are per project, found from the tree the cast was asked from; `coding` is per
# account, so only the user's own config says it, and `None` is no limit.
class Limits(Protocol):
    def processes(self, project_root: str) -> int: ...
    def worktrees(self, project_root: str) -> int: ...
    def prepare(self, project_root: str) -> str | None: ...
    def coding(self) -> int | None: ...


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


# A tree could not be made ready: `git worktree add` refused, or `prepare`
# failed. The cast that wanted it ends with this as its reason.
class TreeError(Exception):
    pass


# A project's pooled worktrees, read off git each time rather than remembered.
# `held` is every tree a live cast stands in, which only the daemon knows.
class Trees(Protocol):
    # A free tree, or a new one while the pool is under `count`; `None` while
    # one is held, as it frees when its cast ends. Raises `TreeError`, also
    # when every tree is blocked or `stuck` — held by a cast awaiting one that
    # waits for a tree — since nothing would free one.
    async def lease(
        self,
        *,
        project_root: str,
        project: str,
        held: set[str],
        stuck: set[str],
        count: int,
    ) -> str | None: ...

    # Once per tree, not per lease. Raises `TreeError`.
    async def prepare(self, tree: str, command: str | None) -> None: ...

    # Why the tree could not be parked, or `None` once it is.
    async def release(self, tree: str) -> str | None: ...
