import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue

from vekna.pacts.casts import CastBoard, Casts, CastView
from vekna.pacts.circle import Exited, Limits, Spawn, Spawned, TreeError, Trees
from vekna.wire import (
    NEEDS_TREE,
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CastQueued,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    RunRecord,
    TreeBlocked,
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
    # `parked` is each awaited cast with the tree its awaiting parent holds.
    # A cast enqueued by another says its need on its hello and is never probed.
    async def run(self, hello: CastHello, parked: dict[str, str]) -> _Ran | None:
        if (cast_id := hello.cast_id) not in self._needs_tree:
            if not hello.worktree:
                exited = await self._spawn(hello, None)
                if exited.code != NEEDS_TREE:
                    return _Ran(exited=exited)
            self._needs_tree[cast_id] = None
        try:
            tree = await self._lease(hello, parked)
        except TreeError:
            del self._needs_tree[cast_id]
            raise
        if tree is None:
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

    # A tree is stuck when the cast holding it awaits one that is itself waiting
    # for a tree: neither ends until the other runs.
    async def _lease(self, hello: CastHello, parked: dict[str, str]) -> str | None:
        root = hello.project_root
        waiting = {cast for cast, tree in self._needs_tree.items() if tree is None}
        async with self._lock(hello.project):
            tree = await self._trees.lease(
                project_root=root,
                project=hello.project,
                held=self._left.trees()
                | {held for held in self._needs_tree.values() if held is not None},
                stuck={tree for child, tree in parked.items() if child in waiting},
                count=self._limits.worktrees(root),
            )
            if tree is not None:
                self._needs_tree[hello.cast_id] = tree
            return tree

    def _lock(self, project: str) -> asyncio.Lock:
        return self._locks.setdefault(project, asyncio.Lock())


# Every cast blocked on another, by request: those whose child has not ended,
# and the answers to those whose child has, due once the parent's slot frees.
# A parent with either holds no process slot.
class Awaits:
    def __init__(
        self, *, hub: CastBoard, records: Callable[[str], RunRecord | None]
    ) -> None:
        self._hub = hub
        # How a cast ended, off the journal: this daemon may never have seen it.
        self._records = records
        self._waiting: dict[str, AwaitRequested] = {}
        self._due: dict[str, AwaitEnded] = {}

    # Said again on every reattach, so a request already held is not news.
    def requested(self, request: AwaitRequested) -> None:
        request_id = request.request_id
        if request_id in self._waiting or request_id in self._due:
            return
        if (reply := self._ending(request)) is None:
            self._waiting[request_id] = request
        else:
            self._due[request_id] = reply

    def withdrawn(self, withdrawn: AwaitWithdrawn) -> None:
        self._waiting.pop(withdrawn.request_id, None)
        self._due.pop(withdrawn.request_id, None)

    # What the cast awaited is dropped, and whatever awaited it is due.
    def ended(self, cast_id: str) -> None:
        for request_id, request in list(self._waiting.items()):
            if request.cast_id == cast_id:
                del self._waiting[request_id]
            elif request.child == cast_id and (reply := self._ending(request)):
                del self._waiting[request_id]
                self._due[request_id] = reply
        self._due = {
            request_id: reply
            for request_id, reply in self._due.items()
            if reply.cast_id != cast_id
        }

    def due(self) -> list[AwaitEnded]:
        return list(self._due.values())

    def answered(self, reply: AwaitEnded) -> None:
        self._due.pop(reply.request_id, None)

    def parked(self) -> set[str]:
        return {request.cast_id for request in self._waiting.values()} | {
            reply.cast_id for reply in self._due.values()
        }

    # Each awaited cast, with the tree its parent stands in.
    def trees(self) -> dict[str, str]:
        return {
            request.child: parent.hello.project_root
            for request in self._waiting.values()
            if (parent := self._hub.casts.get(request.cast_id)) is not None
        }

    # How the child ended, or `None` while it has not. The record says it with
    # the result; a view whose record could not be written says it without.
    # A child nobody has heard of ended before it began, as far as the parent
    # can ever learn.
    def _ending(self, request: AwaitRequested) -> AwaitEnded | None:
        child = request.child
        view = self._hub.casts.get(child)
        if view is not None and view.status in {"queued", "running"}:
            return None
        if (record := self._records(child)) is not None:
            status, detail, result = record.status, record.detail, record.result
        elif view is not None:
            status, detail, result = view.status, view.detail, None
        else:
            return _ended(request, status="error", detail=f"no cast {child}")
        match status:
            case "queued" | "running":
                return None
            case _:
                return _ended(request, status=status, detail=detail, result=result)


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

    def enqueue(self, hello: CastHello) -> None:
        self._hub.apply(hello)
        self._hub.apply(CastQueued(cast_id=hello.cast_id))
        self._queue.append(hello.cast_id)
        self._start()

    # A cast that ended freed its slot, so the queue gets another look, and
    # whatever awaited it can carry on.
    def ended(self, cast_id: str) -> None:
        self._awaits.ended(cast_id)
        self._start()

    def wait_on(self, request: AwaitRequested) -> None:
        self._awaits.requested(request)
        self._start()

    def withdrawn(self, withdrawn: AwaitWithdrawn) -> None:
        self._awaits.withdrawn(withdrawn)
        self._start()

    # A parent comes back before anything queued starts: it was running first,
    # and a child it waited on may be the reason the queue is full.
    def _start(self) -> None:
        for reply in self._awaits.due():
            parent = self._hub.casts.get(reply.cast_id)
            if parent is None or parent.status != "running":
                self._awaits.answered(reply)
            elif self._busy(parent) < self._limits.processes(parent.hello.project_root):
                self._awaits.answered(reply)
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
    async def _run(self, hello: CastHello) -> None:
        cast_id = hello.cast_id
        parked = self._awaits.trees()
        try:
            ran = await self._leasing.run(hello, parked)
        except TreeError as error:
            self._launching.pop(cast_id, None)
            self._failed(cast_id, str(error))
            self._start()
            return
        self._launching.pop(cast_id, None)
        if ran is None:
            # Back in line, and another look only if a cast began awaiting while
            # the lease ran, since that may have stuck every tree. Otherwise the
            # release that frees a tree is what starts the queue again.
            self._queue.insert(0, cast_id)
            if self._awaits.trees() != parked:
                self._start()
            return
        if ran.blocked is not None:
            self._hub.apply(ran.blocked)
        self._failed(cast_id, _why(ran.exited))
        self._start()

    # Written here rather than heard from the cast, so whatever awaits it is
    # told here too.
    def _failed(self, cast_id: str, detail: str) -> None:
        view = self._hub.casts.get(cast_id)
        if view is not None and view.status == "queued":
            self._hub.apply(CastGoodbye(cast_id=cast_id, status="error", detail=detail))
            self._awaits.ended(cast_id)


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
