import asyncio
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from pydantic import JsonValue
from typing_extensions import override

from vekna.pacts.casts import CastBoard, Casts, CastView
from vekna.pacts.circle import (
    CastQueue,
    Exited,
    Limits,
    Spawn,
    Spawned,
    Tending,
    TreeError,
    Trees,
)
from vekna.wire import (
    NEEDS_TREE,
    AltarRequested,
    AwaitEnded,
    AwaitRequested,
    BlockedTree,
    CastGoodbye,
    CastHello,
    CastQueued,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    FailedTree,
    HeldTree,
    ParkedTree,
    RemovedTree,
    RunRecord,
    TendedTree,
    TreeBlocked,
    TreeFreed,
    WireMessage,
)

_log = logging.getLogger(__name__)


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

    def projects(self) -> list[str]:
        return [spawned.project for spawned in self._live()]

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
            status, detail = view.status, view.ending.detail
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
# caused. The lease makes no tree and sets none up: that is the altar's, done
# before any cast, so a cast never waits on a `prepare` or fails in one.
class Leasing:
    def __init__(
        self, *, left: LeftBehind, spawn: Spawn, trees: Trees, limits: Limits
    ) -> None:
        self._left = left
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
                project_root=root, project=hello.project, held=self._held()
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

    # The operator's to clean, so a blocked tree is logged whether or not a
    # window is open.
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
            _log.warning("%s is blocked after cast %s: %s", tree, hello.cast_id, reason)
        return reason

    # Under the lease lock, `prepare` and all, so no tree is leased while it is
    # being tended. Raises `TreeError`.
    async def tend(self, request: AltarRequested, *, project: str) -> list[TendedTree]:
        root = request.project_root
        tending = Tending(
            asked=request,
            project=project,
            count=self._limits.worktrees(root),
            base=self._limits.base(root),
            prepare=self._limits.prepare(root),
        )
        async with self._lock(project):
            trees = await self._trees.tend(tending, self._held())
        for tree in trees:
            failed = isinstance(tree, FailedTree)
            _log.log(logging.WARNING if failed else logging.INFO, _tended(tree))
        return trees

    # A tree leased to a cast not spawned in it yet is held too.
    def _held(self) -> set[str]:
        return self._left.trees() | {
            held for held in self._needs_tree.values() if held is not None
        }

    def _lock(self, project: str) -> asyncio.Lock:
        return self._locks.setdefault(project, asyncio.Lock())


# The daemon's scheduler. A project runs as many casts at once as its
# `processes` says, and the machine as many as `total` says — every running cast
# counts, whether the daemon spawned it or somebody typed `vekna cast` — and a
# queued one is spawned when a slot frees. A cast awaiting another holds no slot
# until the other ends, and then comes back ahead of the queue. The casts a cast
# typed at a terminal set going run one at a time, that cast among them: its
# terminal is one stream, and it reads in order only if one cast writes to it at
# a time.
class Circle(CastQueue):
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

    # A tree that is parked or gone blocks nothing any more. Raises `TreeError`.
    async def tend(self, request: AltarRequested, *, project: str) -> list[TendedTree]:
        trees = await self._leasing.tend(request, project=project)
        for tree in trees:
            if isinstance(tree, (ParkedTree, RemovedTree)):
                self._freed(tree.path)
        return trees

    @override
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
            if self._may_run(self._hub.casts[reply.cast_id]):
                self._hub.apply(reply)
                # A parent that is not attached says its await again on reattach.
                self._hub.tell(reply.cast_id, reply)
        for cast_id in self._in_turn():
            view = self._hub.casts.get(cast_id)
            if view is None or view.status != "queued":
                self._queue.remove(cast_id)
            elif self._may_run(view):
                self._queue.remove(cast_id)
                self._launch(view.hello)

    # Whether a cast in `project_root` may start now. Nothing is held for a cast
    # typed by hand: its hello is what takes the slot.
    # shortcut: two casts typed in the same instant can both be told there is
    # room for the last slot; admitting on the hello itself is the upgrade.
    def has_room(self, *, project_root: str, project: str) -> bool:
        return self._fits(self._holders(), project_root=project_root, project=project)

    # Room that no queued cast is waiting for: all a cast nobody asked for may
    # take.
    @override
    def has_spare(self, *, project_root: str, project: str) -> bool:
        queued = [self._hub.casts[cast_id].hello.project for cast_id in self._queue]
        return self._fits(
            self._holders() + queued, project_root=project_root, project=project
        )

    def _fits(self, holders: list[str], *, project_root: str, project: str) -> bool:
        return (
            holders.count(project) < self._limits.processes(project_root)
            and len(holders) < self._limits.total()
        )

    # The limit that `has_room` ran into; only to be said to a person.
    def why_full(self, *, project_root: str, project: str) -> str:
        holders = self._holders()
        mine, allowed = holders.count(project), self._limits.processes(project_root)
        if mine >= allowed:
            return f"{mine} of {allowed} casts are running in this project"
        total = self._limits.total()
        return f"{len(holders)} of {total} casts are running on this machine"

    # The queue, with what a typed cast's line awaits ahead of the rest: of one
    # cast at a time, the next has to be the one a parked cast is waiting on, or
    # the terminal reads a sibling in the middle of it.
    def _in_turn(self) -> list[str]:
        awaited = {
            request.child
            for view in self._hub.casts.values()
            if self._typed(view) is not None
            for request in view.on_children.values()
        }

        def behind(cast_id: str) -> bool:
            return cast_id not in awaited

        return sorted(self._queue, key=behind)

    def _may_run(self, view: CastView) -> bool:
        hello = view.hello
        if not self.has_room(project_root=hello.project_root, project=hello.project):
            return False
        typed = self._typed(view)
        return typed is None or all(
            self._typed(other) != typed for other in self._active()
        )

    # The cast typed at a terminal that set this one going, itself included, or
    # `None` for a line the daemon was asked to start. Walked up each time: no
    # chain is longer than the casts there are, which bounds a loop a peer sent.
    def _typed(self, view: CastView) -> str | None:
        casts = self._hub.casts
        for _ in casts:
            if (parent := view.hello.enqueued_by) is None:
                return None if view.hello.wired else view.hello.cast_id
            if (found := casts.get(parent)) is None:
                return None
            view = found
        return None

    # Every cast holding a process: running or spawned, and awaiting nothing.
    def _active(self) -> Iterator[CastView]:
        parked = self._awaits.parked()
        for cast_id, view in self._hub.casts.items():
            if cast_id not in parked and (
                view.status == "running" or cast_id in self._launching
            ):
                yield view

    # The project of every cast that holds a slot.
    def _holders(self) -> list[str]:
        return [view.hello.project for view in self._active()] + self._left.projects()

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


# What the daemon's log says of one tree the altar reached.
def _tended(tree: TendedTree) -> str:
    match tree:
        case HeldTree():
            return f"altar held {tree.path}"
        case ParkedTree():
            said = f"altar readied {tree.path}"
        case RemovedTree():
            said = f"altar removed {tree.path}"
        case BlockedTree():
            return f"altar found {tree.path} blocked: {tree.reason}"
        case _:
            said = f"altar failed {tree.path}: {tree.reason}"
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
