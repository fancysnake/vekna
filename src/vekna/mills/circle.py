import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from vekna.pacts.casts import Casts, CastView
from vekna.pacts.circle import Exited, Limits, Spawn, TreeError, Trees
from vekna.wire import (
    NEEDS_TREE,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastQueued,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    TreeBlocked,
    WireMessage,
)


# How a cast's process went: how it exited, and the tree it left blocked if it
# did.
@dataclass(frozen=True, kw_only=True)
class _Ran:
    exited: Exited
    blocked: TreeBlocked | None = None


# Spawns a cast, and once it has said its ritual runs in a worktree, spawns it
# again in a tree leased before the spawn: a lease taken mid-cast would hold a
# slot while it waits, and with every slot waiting that is a deadlock no ritual
# caused.
class Leasing:
    def __init__(
        self,
        *,
        casts: Casts,
        say: Callable[[str], None],
        spawn: Spawn,
        trees: Trees,
        limits: Limits,
    ) -> None:
        self._casts = casts
        self._say = say
        self._spawn = spawn
        self._trees = trees
        self._limits = limits
        # Every cast known to need a tree, with the tree it holds from its lease
        # to its release. Learnt from the cast itself, which exits asking for
        # one: only it can read its ritual. A cast that reattached after a
        # restart holds its tree through its view instead.
        self._needs_tree: dict[str, str | None] = {}
        # One lease or release at a time per project, so two casts never take
        # the same free tree, and a release lands after any lease it raced.
        # `prepare` runs outside it: it takes minutes.
        self._locks: dict[str, asyncio.Lock] = {}

    # `None` when the cast needs a tree and none is free. Raises `TreeError`.
    async def run(self, hello: CastHello) -> _Ran | None:
        if (cast_id := hello.cast_id) not in self._needs_tree:
            exited = await self._spawn(hello, None)
            if exited.code != NEEDS_TREE:
                return _Ran(exited=exited)
            self._needs_tree[cast_id] = None
        if (tree := await self._lease(hello)) is None:
            return None
        try:
            await self._trees.prepare(tree, self._limits.prepare(hello.project_root))
        except TreeError:
            async with self._lock(hello.project):
                del self._needs_tree[cast_id]
            raise
        exited = await self._spawn(hello, tree)
        async with self._lock(hello.project):
            reason = await self._trees.release(tree)
            del self._needs_tree[cast_id]
        if reason is None:
            return _Ran(exited=exited)
        # The operator's to clean, so said where the daemon says things whether
        # or not a window is open.
        self._say(f"{tree} is blocked after cast {cast_id}: {reason}")
        blocked = TreeBlocked(cast_id=cast_id, path=tree, reason=reason)
        return _Ran(exited=exited, blocked=blocked)

    async def _lease(self, hello: CastHello) -> str | None:
        root = hello.project_root
        async with self._lock(hello.project):
            running = {
                view.hello.project_root
                for view in self._casts.casts.values()
                if view.status == "running"
            }
            tree = await self._trees.lease(
                project_root=root,
                project=hello.project,
                held=running | {held for held in self._needs_tree.values() if held},
                count=self._limits.worktrees(root),
            )
            if tree is not None:
                self._needs_tree[hello.cast_id] = tree
            return tree

    def _lock(self, project: str) -> asyncio.Lock:
        return self._locks.setdefault(project, asyncio.Lock())


# The daemon's scheduler. A project runs as many casts at once as its
# `processes` says — every running cast of the project counts, whether the
# daemon spawned it or somebody typed `vekna cast` — and a queued one is spawned
# when a slot frees.
# ponytail: the queue lives in memory. Queued casts left behind by a daemon that
# stopped keep their `queued` records and are not picked up again; reading them
# back at start is the queue's (#141).
class Circle:
    def __init__(
        self,
        *,
        casts: Casts,
        apply: Callable[[CastMessage], None],
        leasing: Leasing,
        limits: Limits,
    ) -> None:
        self._casts = casts
        self._apply = apply
        self._leasing = leasing
        self._limits = limits
        self._queue: list[str] = []
        # Spawned and not yet exited. A cast between its spawn and its hello is
        # still `queued` in the view, and has to hold its slot all the same.
        self._launching: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def enqueue(self, hello: CastHello) -> None:
        self._apply(hello)
        self._apply(CastQueued(cast_id=hello.cast_id))
        self._queue.append(hello.cast_id)
        self._start()

    # A cast that ended freed its slot, so the queue gets another look.
    def ended(self) -> None:
        self._start()

    def _start(self) -> None:
        for cast_id in list(self._queue):
            view = self._casts.casts.get(cast_id)
            if view is None or view.status != "queued":
                self._queue.remove(cast_id)
            elif self._busy(view) < self._limits.processes(view.hello.project_root):
                self._queue.remove(cast_id)
                self._launch(view.hello)

    def _busy(self, queued: CastView) -> int:
        project = queued.hello.project
        return sum(
            1
            for cast_id, view in self._casts.casts.items()
            if view.hello.project == project
            and (view.status == "running" or cast_id in self._launching)
        )

    def _launch(self, hello: CastHello) -> None:
        self._launching.add(hello.cast_id)
        task = asyncio.create_task(self._run(hello))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # A cast still queued once its process has gone never said hello, so its
    # goodbye is the daemon's to write, with whatever the process last said.
    async def _run(self, hello: CastHello) -> None:
        cast_id = hello.cast_id
        try:
            ran = await self._leasing.run(hello)
        except TreeError as error:
            self._launching.discard(cast_id)
            self._failed(cast_id, str(error))
            self._start()
            return
        self._launching.discard(cast_id)
        if ran is None:
            # Back in line without another look: the release that frees a tree
            # is what starts the queue again.
            self._queue.insert(0, cast_id)
            return
        if ran.blocked is not None:
            self._apply(ran.blocked)
        self._failed(cast_id, _why(ran.exited))
        self._start()

    def _failed(self, cast_id: str, detail: str) -> None:
        view = self._casts.casts.get(cast_id)
        if view is not None and view.status == "queued":
            self._apply(CastGoodbye(cast_id=cast_id, status="error", detail=detail))


# How many agent sessions run at once across every cast on the account, granted
# in the order asked.
class CodingPool:
    def __init__(
        self, *, tell: Callable[[str, WireMessage], bool], limits: Limits
    ) -> None:
        self._tell = tell
        self._limits = limits
        self._held: dict[str, str] = {}
        self._waiting: list[CodingSlotRequested] = []

    # However a cast ended, its slots go with it: one that died holding a slot
    # never said it was done.
    def ended(self, cast_id: str) -> None:
        self._held = {held: by for held, by in self._held.items() if by != cast_id}
        self._waiting = [ask for ask in self._waiting if ask.cast_id != cast_id]
        self._grant()

    def requested(self, request: CodingSlotRequested) -> None:
        self._waiting.append(request)
        self._grant()

    # Released before it was granted is a wait the cast gave up on.
    def released(self, release: CodingSlotReleased) -> None:
        self._held.pop(release.request_id, None)
        self._waiting = [
            ask for ask in self._waiting if ask.request_id != release.request_id
        ]
        self._grant()

    def _grant(self) -> None:
        limit = self._limits.coding()
        for ask in list(self._waiting):
            if limit is not None and len(self._held) >= limit:
                return
            self._waiting.remove(ask)
            self._held[ask.request_id] = ask.cast_id
            self._tell(
                ask.cast_id,
                CodingSlotGranted(cast_id=ask.cast_id, request_id=ask.request_id),
            )


def _why(exited: Exited) -> str:
    ended = "would not start" if exited.code is None else f"exited {exited.code}"
    return f"{ended} before its hello: {exited.said}" if exited.said else ended
