import asyncio
from datetime import UTC, datetime

import pytest

from vekna.mills.circle import Circle, CodingPool
from vekna.mills.hub import Hub
from vekna.pacts.circle import Exited, Limits, TreeError, Trees
from vekna.pacts.routing import Surface
from vekna.wire import (
    NEEDS_TREE,
    CastGoodbye,
    CastHello,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    TreeBlocked,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _Limits(Limits):
    def __init__(
        self, *, processes: int = 1, worktrees: int = 2, coding: int | None = None
    ) -> None:
        self._processes = processes
        self._worktrees = worktrees
        self.prepares = "make venv"
        self._coding = coding
        self.asked: list[str] = []

    def processes(self, project_root: str) -> int:
        self.asked.append(project_root)
        return self._processes

    def worktrees(self, project_root: str) -> int:
        del project_root
        return self._worktrees

    def prepare(self, project_root: str) -> str | None:
        del project_root
        return self.prepares

    def coding(self) -> int | None:
        return self._coding


# Each spawned cast runs until the test says how it ended.
class _Spawn:
    def __init__(self) -> None:
        self.spawned: list[str] = []
        self.trees: list[str | None] = []
        self._exits: dict[str, asyncio.Future[Exited]] = {}

    async def __call__(self, hello: CastHello, tree: str | None) -> Exited:
        self.spawned.append(hello.cast_id)
        self.trees.append(tree)
        future = asyncio.get_running_loop().create_future()
        self._exits[hello.cast_id] = future
        return await future

    def exit(self, cast_id: str, *, code: int = 0, said: str = "") -> None:
        self._exits[cast_id].set_result(Exited(code=code, said=said))


# A pool of named trees, each free until leased; `blocked` is what releasing
# the named tree answers.
class _Trees(Trees):
    def __init__(self, *free: str) -> None:
        self.free = list(free)
        self.blocked: dict[str, str] = {}
        self.leases: list[dict[str, object]] = []
        self.released: list[str] = []
        self.refuse: str | None = None

    async def lease(
        self,
        *,
        project_root: str,
        project: str,
        held: set[str],
        count: int,
        prepare: str | None,
    ) -> str | None:
        self.leases.append(
            {
                "project_root": project_root,
                "project": project,
                "held": held,
                "count": count,
                "prepare": prepare,
            }
        )
        if self.refuse is not None:
            raise TreeError(self.refuse)
        return self.free.pop(0) if self.free else None

    async def release(self, tree: str) -> str | None:
        self.released.append(tree)
        if (reason := self.blocked.get(tree)) is not None:
            return reason
        self.free.append(tree)
        return None


class _Peer(Surface):
    def __init__(self) -> None:
        self.sent: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.sent.append(message)


def _hello(cast_id: str, *, project: str = "/proj/.git") -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        project=project,
        ritual="nap",
        components={},
        started_at=_WHEN,
        wired=True,
    )


def _circle(limits: _Limits, trees: _Trees | None = None) -> tuple[Circle, Hub, _Spawn]:
    hub, spawn = Hub(), _Spawn()
    circle = Circle(
        casts=hub, apply=hub.apply, spawn=spawn, trees=trees or _Trees(), limits=limits
    )
    return circle, hub, spawn


def _pool(limits: _Limits) -> tuple[CodingPool, Hub]:
    hub = Hub()
    return CodingPool(tell=hub.tell, limits=limits), hub


async def _settled() -> None:
    for _ in range(3):
        await asyncio.sleep(0)


@pytest.mark.asyncio
class TestProcesses:
    @staticmethod
    async def test_a_cast_past_the_limit_waits_queued():
        circle, hub, spawn = _circle(_Limits(processes=1))

        circle.enqueue(_hello("c1"))
        circle.enqueue(_hello("c2"))
        await _settled()

        assert spawn.spawned == ["c1"]
        assert hub.casts["c2"].status == "queued"

    # Between its spawn and its hello a cast is still `queued` in the view, and
    # holds its slot all the same.
    @staticmethod
    async def test_a_cast_that_has_not_said_hello_yet_holds_its_slot():
        circle, _, spawn = _circle(_Limits(processes=1))
        circle.enqueue(_hello("c1"))
        await _settled()

        circle.enqueue(_hello("c2"))
        await _settled()

        assert spawn.spawned == ["c1"]

    @staticmethod
    async def test_the_next_one_starts_when_a_process_exits():
        circle, hub, spawn = _circle(_Limits(processes=1))
        circle.enqueue(_hello("c1"))
        circle.enqueue(_hello("c2"))
        await _settled()
        hub.apply(_hello("c1"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))

        spawn.exit("c1")
        await _settled()

        assert spawn.spawned == ["c1", "c2"]

    # Counting what is running in the project, not what this daemon spawned:
    # a `vekna cast` typed by hand takes a slot too.
    @staticmethod
    async def test_a_cast_run_by_hand_takes_a_slot():
        circle, hub, spawn = _circle(_Limits(processes=1))
        hub.apply(_hello("by-hand"))

        circle.enqueue(_hello("c1"))
        await _settled()
        assert not spawn.spawned

        hub.apply(CastGoodbye(cast_id="by-hand", status="ok"))
        circle.ended()
        await _settled()
        assert spawn.spawned == ["c1"]

    @staticmethod
    async def test_a_queued_cast_that_ends_before_its_turn_is_never_spawned():
        circle, hub, spawn = _circle(_Limits(processes=1))
        circle.enqueue(_hello("c1"))
        circle.enqueue(_hello("c2"))
        await _settled()
        hub.apply(CastGoodbye(cast_id="c2", status="error", detail="cancelled"))
        circle.ended()
        hub.apply(_hello("c1"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))

        spawn.exit("c1")
        await _settled()

        assert spawn.spawned == ["c1"]
        assert hub.casts["c2"].status == "error"

    @staticmethod
    async def test_each_project_counts_its_own():
        circle, _, spawn = _circle(_Limits(processes=1))

        circle.enqueue(_hello("c1", project="/one/.git"))
        circle.enqueue(_hello("c2", project="/two/.git"))
        await _settled()

        assert spawn.spawned == ["c1", "c2"]

    # A ritual that is not there dies before its hello, so the only goodbye it
    # gets is the one written here, with what the process last said.
    @staticmethod
    async def test_a_cast_that_dies_before_its_hello_fails_saying_why():
        circle, hub, spawn = _circle(_Limits())
        circle.enqueue(_hello("c1"))
        await _settled()

        spawn.exit("c1", code=2, said="no ritual named 'nap'")
        await _settled()

        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == (
            "exited 2 before its hello: no ritual named 'nap'"
        )


# A cast learns its ritual wants a tree only once spawned, so it exits saying so
# and is queued again: this is where the pool is taken.
async def _asked_for_a_tree(circle: Circle, spawn: _Spawn, cast_id: str) -> None:
    circle.enqueue(_hello(cast_id))
    await _settled()
    spawn.exit(cast_id, code=NEEDS_TREE)
    await _settled()


@pytest.mark.asyncio
class TestTrees:
    @staticmethod
    async def test_a_cast_that_needs_a_tree_runs_again_in_one_it_leased():
        trees = _Trees("/pool/1")
        circle, hub, spawn = _circle(_Limits(worktrees=3), trees)

        await _asked_for_a_tree(circle, spawn, "c1")

        assert spawn.spawned == ["c1", "c1"]
        assert spawn.trees == [None, "/pool/1"]
        assert hub.casts["c1"].status == "queued"
        assert trees.leases == [
            {
                "project_root": "/proj",
                "project": "/proj/.git",
                "held": set(),
                "count": 3,
                "prepare": "make venv",
            }
        ]

    @staticmethod
    async def test_the_tree_is_released_when_the_cast_exits():
        trees = _Trees("/pool/1")
        circle, _, spawn = _circle(_Limits(), trees)
        await _asked_for_a_tree(circle, spawn, "c1")

        spawn.exit("c1")
        await _settled()

        assert trees.released == ["/pool/1"]

    @staticmethod
    async def test_with_no_free_tree_it_waits_queued_until_one_is_released():
        trees = _Trees("/pool/1")
        circle, hub, spawn = _circle(_Limits(processes=2), trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        await _asked_for_a_tree(circle, spawn, "c2")
        assert spawn.trees == [None, "/pool/1", None]
        assert hub.casts["c2"].status == "queued"

        hub.apply(_hello("c1"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        spawn.exit("c1")
        await _settled()

        assert spawn.trees == [None, "/pool/1", None, "/pool/1"]

    # A reattached cast after a restart is in no lease of this daemon's, but
    # the tree it stands in is held all the same.
    @staticmethod
    async def test_a_tree_a_running_cast_stands_in_is_held():
        trees = _Trees("/pool/2")
        circle, hub, spawn = _circle(_Limits(processes=2), trees)
        hub.apply(_hello("earlier").model_copy(update={"project_root": "/pool/1"}))

        await _asked_for_a_tree(circle, spawn, "c1")

        assert trees.leases[0]["held"] == {"/pool/1"}

    @staticmethod
    async def test_a_tree_that_cannot_be_made_ready_fails_the_cast():
        trees = _Trees()
        trees.refuse = "prepare exited 1"
        circle, hub, spawn = _circle(_Limits(), trees)

        await _asked_for_a_tree(circle, spawn, "c1")

        assert spawn.spawned == ["c1"]
        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == "prepare exited 1"

    @staticmethod
    async def test_a_tree_left_dirty_is_reported_against_its_cast():
        trees = _Trees("/pool/1")
        trees.blocked["/pool/1"] = "uncommitted changes"
        circle, hub, spawn = _circle(_Limits(), trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        hub.apply(_hello("c1"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))

        spawn.exit("c1")
        await _settled()

        assert hub.casts["c1"].blocked == TreeBlocked(
            cast_id="c1", path="/pool/1", reason="uncommitted changes"
        )
        assert not trees.free


@pytest.mark.asyncio
class TestCodingSlots:
    @staticmethod
    async def test_slots_are_granted_up_to_the_limit_in_the_order_asked():
        pool, hub = _pool(_Limits(coding=1))
        peer = _Peer()
        hub.open_cast("c1", peer)

        pool.requested(CodingSlotRequested(cast_id="c1", request_id="s1"))
        pool.requested(CodingSlotRequested(cast_id="c1", request_id="s2"))
        assert peer.sent == [CodingSlotGranted(cast_id="c1", request_id="s1")]

        pool.released(CodingSlotReleased(cast_id="c1", request_id="s1"))
        assert peer.sent[-1] == CodingSlotGranted(cast_id="c1", request_id="s2")

    @staticmethod
    async def test_no_limit_grants_every_one():
        pool, hub = _pool(_Limits(coding=None))
        peer = _Peer()
        hub.open_cast("c1", peer)

        asked = [
            CodingSlotRequested(cast_id="c1", request_id=f"s{n}") for n in range(3)
        ]
        for request in asked:
            pool.requested(request)

        assert len(peer.sent) == len(asked)

    # A cast that died mid-session never said it was done.
    @staticmethod
    async def test_a_cast_that_ends_gives_its_slots_back():
        pool, hub = _pool(_Limits(coding=1))
        first, second = _Peer(), _Peer()
        hub.open_cast("c1", first)
        hub.open_cast("c2", second)
        pool.requested(CodingSlotRequested(cast_id="c1", request_id="s1"))
        pool.requested(CodingSlotRequested(cast_id="c2", request_id="s2"))

        pool.ended("c1")

        assert second.sent == [CodingSlotGranted(cast_id="c2", request_id="s2")]

    @staticmethod
    async def test_a_wait_given_up_is_never_granted():
        pool, hub = _pool(_Limits(coding=1))
        peer = _Peer()
        hub.open_cast("c1", peer)
        pool.requested(CodingSlotRequested(cast_id="c1", request_id="s1"))
        pool.requested(CodingSlotRequested(cast_id="c1", request_id="s2"))

        pool.released(CodingSlotReleased(cast_id="c1", request_id="s2"))
        pool.released(CodingSlotReleased(cast_id="c1", request_id="s1"))

        assert peer.sent == [CodingSlotGranted(cast_id="c1", request_id="s1")]
