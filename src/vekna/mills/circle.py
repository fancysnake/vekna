import asyncio
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from vekna.pacts.casts import CastBoard, Casts, CastView
from vekna.pacts.circle import Exited, Limits, Spawn, Spawned, TreeError, Trees
from vekna.wire import (
    NEEDS_TREE,
    AwaitEnded,
    AwaitRequested,
    CastGoodbye,
    CastHello,
    CastQueued,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    HeldTree,
    ParkedTree,
    PurifiedTree,
    RunRecord,
    TreeBlocked,
    TreeFreed,
    WireMessage,
)


# How a cast's process went: how it exited, and the tree it left blocked if it
# did.
@dataclass(frozen=True, kw_only=True)
class _Ran:
    exited: Exited
    blocked: TreeBlocked | None = None


# The casts a stopped daemon left running, which the views do not have until
# they reattach. Each holds its slot and its tree until then, or until its
# process is gone.
# shortcut: a cast that dies before it reattaches wakes no queued cast, which
# waits for the next cast to end; a timer would wake it once #141 persists the
# queue.
class LeftBehind:
    def __init__(
        self, *, casts: Casts, spawned: list[Spawned], alive: Callable[[int], bool]
    ) -> None:
        self._casts = casts
        self._spawned = spawned
        self._alive = alive

    # Every tree a running cast stands in, whether a view says so or it was left
    # behind. A view's `project_root` is the tree: a leased cast says hello from
    # where it was spawned. A tree leased to a cast not running yet is Leasing's.
    def trees(self) -> set[str]:
        return {
            view.hello.project_root
            for view in self._casts.casts.values()
            if view.status == "running"
        } | {spawned.tree for spawned in self._live() if spawned.tree is not None}

    # The trees of the running casts that await any of `children`, off the
    # views, which hold each await until it is answered.
    def awaiting(self, children: set[str]) -> set[str]:
        return {
            view.hello.project_root
            for view in self._casts.casts.values()
            if any(request.child in children for request in view.on_children.values())
        }

    def count(self, project: str) -> int:
        return sum(1 for spawned in self._live() if spawned.project == project)

    # Dropped for good once either is true, since neither comes back: a view
    # stays in the hub, and a pid that is gone and reused is somebody else's.
    def _live(self) -> list[Spawned]:
        self._spawned = [
            spawned
            for spawned in self._spawned
            if spawned.cast_id not in self._casts.casts and self._alive(spawned.pid)
        ]
        return self._spawned


# Every cast blocked on another, read off the views: a parent's `on_children`
# holds each request until it is answered or withdrawn, or the parent ends. A
# parent with any holds no process slot.
class Awaits:
    def __init__(
        self, *, hub: CastBoard, records: Callable[[str], RunRecord | None]
    ) -> None:
        self._hub = hub
        # How a cast ended, off the journal: this daemon may never have seen it.
        self._records = records
        # Each ending found, by request: an ending never changes, and finding it
        # reads the disk.
        self._ended: dict[str, AwaitEnded] = {}

    # The answers to the requests whose child has ended, due once the parent's
    # slot frees.
    def due(self) -> list[AwaitEnded]:
        ended: dict[str, AwaitEnded] = {}
        for request in self._requests():
            reply = self._ended.get(request.request_id) or self._ending(request)
            if reply is not None:
                ended[request.request_id] = reply
        self._ended = ended
        return list(ended.values())

    def parked(self) -> set[str]:
        return {
            cast_id for cast_id, view in self._hub.casts.items() if view.on_children
        }

    def _requests(self) -> Iterator[AwaitRequested]:
        for view in self._hub.casts.values():
            yield from view.on_children.values()

    # How the child ended, or `None` while it has not. The view says it first:
    # a goodbye whose record could not be written leaves the record running.
    # The result is the record's alone, once it says the same ending. A child
    # nobody has heard of ended before it began, as far as the parent can ever
    # learn.
    def _ending(self, request: AwaitRequested) -> AwaitEnded | None:
        child = request.child
        view = self._hub.casts.get(child)
        if view is not None and view.status in {"queued", "running"}:
            return None
        record = self._records(child)
        if view is not None:
            status, detail = view.status, view.detail
        elif record is not None:
            status, detail = record.status, record.detail
        else:
            return _ended(request, status="error", detail=f"no cast {child}")
        result = (
            record.result if record is not None and record.status == status else None
        )
        match status:
            case "queued" | "running":
                return None
            case _:
                return _ended(request, status=status, detail=detail, result=result)


# Spawns a cast, and once it has said its ritual runs in a worktree, spawns it
# again in a tree leased before the spawn: a lease taken mid-cast would hold a
# slot while it waits, and with every slot waiting that is a deadlock no ritual
# caused.
class Leasing:
    def __init__(
        self,
        *,
        left: LeftBehind,
        say: Callable[[str], None],
        spawn: Spawn,
        trees: Trees,
        limits: Limits,
    ) -> None:
        self._left = left
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
    # A cast enqueued by another says its need on its hello and is never probed.
    # However its turn ends, short of waiting for a tree, the cast gives back
    # its entry and whatever tree it leased. `parked` is told each tree a lease
    # or a release parks.
    async def run(
        self, hello: CastHello, *, parked: Callable[[str], None]
    ) -> _Ran | None:
        if (cast_id := hello.cast_id) not in self._needs_tree:
            if not hello.worktree:
                exited = await self._spawn(hello, None)
                if exited.code != NEEDS_TREE:
                    return _Ran(exited=exited)
            self._needs_tree[cast_id] = None
        tree: str | None = None
        try:
            if (tree := await self._lease(hello)) is None:
                return None
            parked(tree)
            await self._trees.prepare(tree, self._limits.prepare(hello.project_root))
            exited = await self._spawn(hello, tree)
        except BaseException:
            await self._release(hello, tree, parked)
            raise
        if (reason := await self._release(hello, tree, parked)) is None:
            return _Ran(exited=exited)
        blocked = TreeBlocked(cast_id=cast_id, path=tree, reason=reason)
        return _Ran(exited=exited, blocked=blocked)

    # A tree is stuck when the cast holding it awaits one that is itself waiting
    # for a tree: neither ends until the other runs. Read once the lease is
    # back, so an await that landed while it ran counts.
    async def _lease(self, hello: CastHello) -> str | None:
        root = hello.project_root
        async with self._lock(hello.project):
            found = await self._trees.lease(
                project_root=root,
                project=hello.project,
                held=self._held(),
                count=self._limits.worktrees(root),
            )
            if isinstance(found, str):
                self._needs_tree[hello.cast_id] = found
                return found
            waiting = {cast for cast, tree in self._needs_tree.items() if tree is None}
            if found.held <= self._left.awaiting(waiting):
                msg = (
                    "every tree is blocked or held by a cast awaiting one that needs a"
                    f" tree: {', '.join(sorted(found.held))}"
                )
                raise TreeError(msg)
            return None

    # The operator's to clean, so a blocked tree is said where the daemon says
    # things whether or not a window is open.
    async def _release(
        self, hello: CastHello, tree: str | None, parked: Callable[[str], None]
    ) -> str | None:
        async with self._lock(hello.project):
            reason = None if tree is None else await self._trees.release(tree)
            del self._needs_tree[hello.cast_id]
        if tree is None:
            return None
        if reason is None:
            parked(tree)
        else:
            self._say(f"{tree} is blocked after cast {hello.cast_id}: {reason}")
        return reason

    # Under the lease lock, so no tree is leased while it is being purified.
    # Raises `TreeError`.
    async def purify(
        self, *, project_root: str, project: str, save: bool
    ) -> list[PurifiedTree]:
        async with self._lock(project):
            trees = await self._trees.purify(
                project_root=project_root, project=project, held=self._held(), save=save
            )
        for tree in trees:
            self._say(_purified(tree))
        return trees

    # A tree leased to a cast still preparing it is held too.
    def _held(self) -> set[str]:
        return self._left.trees() | {
            held for held in self._needs_tree.values() if held is not None
        }

    def _lock(self, project: str) -> asyncio.Lock:
        return self._locks.setdefault(project, asyncio.Lock())


# The daemon's scheduler. A project runs as many casts at once as its
# `processes` says — every running cast of the project counts, whether the
# daemon spawned it or somebody typed `vekna cast` — and a queued one is spawned
# when a slot frees. A cast awaiting another holds no slot until the other ends,
# and then comes back ahead of the queue.
class Circle:
    def __init__(
        self,
        *,
        hub: CastBoard,
        left: LeftBehind,
        leasing: Leasing,
        limits: Limits,
        awaits: Awaits,
    ) -> None:
        self._hub = hub
        self._left = left
        self._leasing = leasing
        self._limits = limits
        self._awaits = awaits
        self._queue: list[str] = []
        # Spawned and not yet exited. A cast between its spawn and its hello is
        # still `queued` in the view, and has to hold its slot all the same.
        self._launching: dict[str, asyncio.Task[None]] = {}

    # Raises `TreeError`.
    async def purify(
        self, *, project_root: str, project: str, save: bool
    ) -> list[PurifiedTree]:
        trees = await self._leasing.purify(
            project_root=project_root, project=project, save=save
        )
        for tree in trees:
            if isinstance(tree, ParkedTree):
                self._freed(tree.path)
        return trees

    def enqueue(self, hello: CastHello) -> None:
        self._hub.apply(hello)
        self._hub.apply(CastQueued(cast_id=hello.cast_id))
        self._queue.append(hello.cast_id)
        self._start()

    # Told once the hub has the news, of whatever may let a cast run: one that
    # ended freed its slot, and whatever awaited it can carry on; one that
    # began awaiting gave its slot up, and may have stuck every tree; one that
    # stopped awaiting took its slot back.
    def wake(self) -> None:
        self._start()

    # A parent comes back before anything queued starts: it was running first,
    # and a child it waited on may be the reason the queue is full.
    def _start(self) -> None:
        for reply in self._awaits.due():
            parent = self._hub.casts[reply.cast_id]
            if self._busy(parent) < self._limits.processes(parent.hello.project_root):
                self._hub.apply(reply)
                # A parent that is not attached says its await again on reattach.
                self._hub.tell(reply.cast_id, reply)
        for cast_id in list(self._queue):
            view = self._hub.casts.get(cast_id)
            if view is None or view.status != "queued":
                self._queue.remove(cast_id)
            elif self._busy(view) < self._limits.processes(view.hello.project_root):
                self._queue.remove(cast_id)
                self._launch(view.hello)

    def _busy(self, queued: CastView) -> int:
        project = queued.hello.project
        parked = self._awaits.parked()
        return sum(
            1
            for cast_id, view in self._hub.casts.items()
            if view.hello.project == project
            and cast_id not in parked
            and (view.status == "running" or cast_id in self._launching)
        ) + self._left.count(project)

    # Held until the cast's process has gone: the task is its only reference.
    def _launch(self, hello: CastHello) -> None:
        self._launching[hello.cast_id] = asyncio.create_task(self._run(hello))

    # A cast still queued once its process has gone never said hello, so its
    # goodbye is the daemon's to write, with whatever the process last said.
    # Only a `TreeError` is expected; anything else fails the cast all the same,
    # and is raised on for the loop to report.
    async def _run(self, hello: CastHello) -> None:
        cast_id = hello.cast_id
        try:
            try:
                ran = await self._leasing.run(hello, parked=self._freed)
            finally:
                del self._launching[cast_id]
        except Exception as error:
            self._failed(cast_id, str(error))
            self._start()
            if isinstance(error, TreeError):
                return
            raise
        if ran is None:
            # Back in line: the release that frees a tree, or an await that
            # sticks every tree, is what starts the queue again.
            self._queue.insert(0, cast_id)
            return
        if ran.blocked is not None:
            self._hub.apply(ran.blocked)
        self._failed(cast_id, _why(ran.exited))
        self._start()

    # A parked tree is back in the pool, so whatever cast left it blocked is
    # told the block is over, and no window goes on showing it.
    def _freed(self, tree: str) -> None:
        for cast_id, view in self._hub.casts.items():
            if view.blocked is not None and view.blocked.path == tree:
                self._hub.apply(TreeFreed(cast_id=cast_id, path=tree))

    def _failed(self, cast_id: str, detail: str) -> None:
        view = self._hub.casts.get(cast_id)
        if view is not None and view.status == "queued":
            self._hub.apply(CastGoodbye(cast_id=cast_id, status="error", detail=detail))


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


# What the daemon's log says of one tree `purify` reached.
def _purified(tree: PurifiedTree) -> str:
    match tree:
        case HeldTree():
            return f"purify held {tree.path}"
        case ParkedTree():
            said = f"purify parked {tree.path}"
        case _:
            said = f"purify failed {tree.path}: {tree.reason}"
    if tree.saved is None:
        return said
    return f"{said}, its uncommitted work on {tree.saved}"


def _ended(
    request: AwaitRequested,
    *,
    status: Literal["ok", "error", "disconnected"],
    detail: str | None,
    result: JsonValue | None = None,
) -> AwaitEnded:
    return AwaitEnded(
        cast_id=request.cast_id,
        request_id=request.request_id,
        child=request.child,
        status=status,
        detail=detail,
        result=result,
    )


def _why(exited: Exited) -> str:
    ended = "would not start" if exited.code is None else f"exited {exited.code}"
    return f"{ended} before its hello: {exited.said}" if exited.said else ended
