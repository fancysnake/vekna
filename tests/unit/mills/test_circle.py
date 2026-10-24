import asyncio
from datetime import UTC, datetime

import pytest

from vekna.mills.circle import Awaits, Circle, CodingPool, Leasing, LeftBehind
from vekna.mills.hub import Hub
from vekna.pacts.circle import Exited, Full, Limits, Spawned, TreeError, Trees
from vekna.pacts.routing import Surface
from vekna.wire import (
    NEEDS_TREE,
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    RunRecord,
    TreeBlocked,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _Limits(Limits):
    def __init__(
        self, *, processes: int = 1, worktrees: int = 2, coding: int | None = None
    ) -> None:
        self.slots = processes
        self._worktrees = worktrees
        self.prepares = "make venv"
        self._coding = coding
        self.asked: list[str] = []
        self.asked_trees: list[str] = []
        self.asked_prepares: list[str] = []

    def processes(self, project_root: str) -> int:
        self.asked.append(project_root)
        return self.slots

    def worktrees(self, project_root: str) -> int:
        self.asked_trees.append(project_root)
        return self._worktrees

    def prepare(self, project_root: str) -> str | None:
        self.asked_prepares.append(project_root)
        return self.prepares

    def coding(self) -> int | None:
        return self._coding


# Each spawned cast runs until the test says how it ended.
class _Spawn:
    def __init__(self) -> None:
        self.spawned: list[str] = []
        self.trees: list[str | None] = []
        self._exits: dict[str, asyncio.Future[Exited]] = {}
        # What the next spawn raises, as the mark it writes may.
        self.raising: OSError | None = None

    async def __call__(self, hello: CastHello, tree: str | None) -> Exited:
        self.spawned.append(hello.cast_id)
        self.trees.append(tree)
        if (error := self.raising) is not None:
            self.raising = None
            raise error
        future = asyncio.get_running_loop().create_future()
        self._exits[hello.cast_id] = future
        return await future

    def exit(self, cast_id: str, *, code: int | None = 0, said: str = "") -> None:
        self._exits[cast_id].set_result(Exited(code=code, said=said))


# A pool of named trees, each free until leased; `blocked` is what releasing
# the named tree answers.
class _Trees(Trees):
    def __init__(self, *free: str) -> None:
        self.free = list(free)
        self.blocked: dict[str, str] = {}
        self.leases: list[dict[str, object]] = []
        self.prepared: list[tuple[str, str | None]] = []
        self.released: list[str] = []
        # What a lease or a prepare waits on before it is done, or fails with.
        self.leasing: asyncio.Future[None] | None = None
        self.preparing: asyncio.Future[None] | None = None

    async def lease(
        self, *, project_root: str, project: str, held: set[str], count: int
    ) -> str | Full:
        self.leases.append(
            {
                "project_root": project_root,
                "project": project,
                "held": held,
                "count": count,
            }
        )
        if self.leasing is not None:
            await self.leasing
        if self.free:
            return self.free.pop(0)
        if not held:
            msg = "every tree is blocked"
            raise TreeError(msg)
        return Full(held=frozenset(held))

    async def prepare(self, tree: str, command: str | None) -> None:
        self.prepared.append((tree, command))
        if self.preparing is not None:
            await self.preparing

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


def _hello(
    cast_id: str,
    *,
    project: str = "/proj/.git",
    root: str = "/proj",
    worktree: bool = False,
) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root=root,
        worktree=worktree,
        project=project,
        ritual="nap",
        components={},
        started_at=_WHEN,
        wired=True,
    )


# Which pids are alive, every pid asked about, and the casts left running.
class _Alive:
    def __init__(self, *pids: int, left: list[Spawned] | None = None) -> None:
        self.pids = set(pids)
        self.left = left or []
        self.asked: list[int] = []

    def __call__(self, pid: int) -> bool:
        self.asked.append(pid)
        return pid in self.pids


def _circle(
    limits: _Limits,
    trees: _Trees | None = None,
    said: list[str] | None = None,
    *,
    alive: _Alive | None = None,
    records: dict[str, RunRecord] | None = None,
) -> tuple[Circle, Hub, _Spawn]:
    hub, spawn = Hub(), _Spawn()
    alive = alive or _Alive()
    behind = LeftBehind(casts=hub, spawned=alive.left, alive=alive)
    leasing = Leasing(
        left=behind,
        say=([] if said is None else said).append,
        spawn=spawn,
        trees=trees or _Trees(),
        limits=limits,
    )
    circle = Circle(
        hub=hub,
        left=behind,
        leasing=leasing,
        limits=limits,
        awaits=Awaits(hub=hub, records=(records or {}).get),
    )
    return circle, hub, spawn


def _left(cast_id: str, *, pid: int, tree: str | None) -> Spawned:
    return Spawned(cast_id=cast_id, pid=pid, project="/proj/.git", tree=tree)


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
        limits = _Limits(processes=1)
        circle, hub, spawn = _circle(limits)

        circle.enqueue(_hello("c1"))
        circle.enqueue(_hello("c2"))
        await _settled()

        assert spawn.spawned == ["c1"]
        assert hub.casts["c2"].status == "queued"
        assert limits.asked == ["/proj", "/proj"]

    @staticmethod
    async def test_the_limit_is_how_many_run_at_once():
        circle, _, spawn = _circle(_Limits(processes=2))

        for cast_id in ("c1", "c2", "c3"):
            circle.enqueue(_hello(cast_id))
        await _settled()

        assert spawn.spawned == ["c1", "c2"]

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
        assert hub.casts["c1"].status == "ok"
        assert hub.casts["c1"].detail is None

    @staticmethod
    async def test_a_cast_that_has_exited_leaves_the_loop_nothing_to_report():
        errors: list[dict[str, object]] = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _, context: errors.append(context)
        )
        circle, _, spawn = _circle(_Limits())
        circle.enqueue(_hello("c1"))
        await _settled()

        spawn.exit("c1")
        await _settled()

        assert not errors

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
        circle.wake()
        await _settled()
        assert spawn.spawned == ["c1"]

    @staticmethod
    async def test_a_cast_left_running_takes_a_slot_until_it_reattaches():
        alive = _Alive(7, left=[_left("before", pid=7, tree=None)])
        circle, hub, spawn = _circle(_Limits(processes=1), alive=alive)

        circle.enqueue(_hello("c1"))
        await _settled()
        assert not spawn.spawned

        hub.apply(_hello("before"))
        hub.apply(CastGoodbye(cast_id="before", status="ok"))
        circle.wake()
        await _settled()
        assert spawn.spawned == ["c1"]
        assert alive.asked == [7]

    @staticmethod
    async def test_a_queued_cast_that_ends_before_its_turn_is_never_spawned():
        circle, hub, spawn = _circle(_Limits(processes=1))
        circle.enqueue(_hello("c1"))
        circle.enqueue(_hello("c2"))
        await _settled()
        hub.apply(CastGoodbye(cast_id="c2", status="error", detail="cancelled"))
        circle.wake()
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
    @pytest.mark.parametrize(
        ("code", "said", "why"),
        [
            (
                2,
                "no ritual named 'nap'",
                "exited 2 before its hello: no ritual named 'nap'",
            ),
            (None, "no such file", "would not start before its hello: no such file"),
            (3, "", "exited 3"),
        ],
    )
    async def test_a_cast_that_dies_before_its_hello_fails_saying_why(
        code: int | None, said: str, why: str
    ):
        circle, hub, spawn = _circle(_Limits())
        circle.enqueue(_hello("c1"))
        await _settled()

        spawn.exit("c1", code=code, said=said)
        await _settled()

        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == why


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
        limits = _Limits(worktrees=3)
        circle, hub, spawn = _circle(limits, trees)

        await _asked_for_a_tree(circle, spawn, "c1")

        assert limits.asked_trees == ["/proj"]
        assert limits.asked_prepares == ["/proj"]
        assert spawn.spawned == ["c1", "c1"]
        assert spawn.trees == [None, "/pool/1"]
        assert hub.casts["c1"].status == "queued"
        assert trees.leases == [
            {
                "project_root": "/proj",
                "project": "/proj/.git",
                "held": set(),
                "count": 3,
            }
        ]
        assert trees.prepared == [("/pool/1", "make venv")]

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
        assert trees.leases[1]["held"] == {"/pool/1"}
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

    # A daemon restarted under a running cast hears from it only once it
    # reattaches, seconds later; its process says it is there before that.
    @staticmethod
    async def test_a_tree_a_cast_left_running_stands_in_is_held():
        trees = _Trees("/pool/2")
        left = [_left("before", pid=7, tree="/pool/1")]
        circle, _, spawn = _circle(
            _Limits(processes=2), trees, alive=_Alive(7, left=left)
        )

        await _asked_for_a_tree(circle, spawn, "c1")

        assert trees.leases[0]["held"] == {"/pool/1"}

    @staticmethod
    async def test_a_tree_whose_cast_is_gone_is_not_held():
        trees = _Trees("/pool/1")
        alive = _Alive(left=[_left("before", pid=7, tree="/pool/1")])
        circle, _, spawn = _circle(_Limits(processes=2), trees, alive=alive)

        await _asked_for_a_tree(circle, spawn, "c1")

        assert trees.leases[0]["held"] == set()
        assert alive.asked == [7]

    # Read at the lease, not at the spawn before it, which takes seconds.
    @staticmethod
    async def test_a_cast_that_said_hello_while_the_probe_ran_is_held():
        trees = _Trees("/pool/2")
        circle, hub, spawn = _circle(_Limits(processes=2), trees)
        circle.enqueue(_hello("c1"))
        await _settled()
        hub.apply(_hello("earlier").model_copy(update={"project_root": "/pool/1"}))

        spawn.exit("c1", code=NEEDS_TREE)
        await _settled()

        assert trees.leases[0]["held"] == {"/pool/1"}

    @staticmethod
    async def test_a_lease_that_fails_fails_the_cast():
        trees = _Trees()
        refused = "every tree is blocked: /pool/1 (uncommitted changes)"
        trees.leasing = asyncio.get_running_loop().create_future()
        trees.leasing.set_exception(TreeError(refused))
        circle, hub, spawn = _circle(_Limits(), trees)

        await _asked_for_a_tree(circle, spawn, "c1")

        assert spawn.spawned == ["c1"]
        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == refused

    # The tree goes back to the pool, so the next cast leases it again.
    @staticmethod
    async def test_a_tree_that_cannot_be_made_ready_fails_the_cast():
        trees = _Trees("/pool/1")
        trees.preparing = asyncio.get_running_loop().create_future()
        trees.preparing.set_exception(TreeError("prepare exited 1"))
        circle, hub, spawn = _circle(_Limits(processes=2), trees)

        await _asked_for_a_tree(circle, spawn, "c1")
        trees.preparing = None
        await _asked_for_a_tree(circle, spawn, "c2")

        assert spawn.spawned == ["c1", "c2", "c2"]
        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == "prepare exited 1"
        assert trees.leases[1]["held"] == set()
        assert spawn.trees[-1] == "/pool/1"

    # A prepare takes minutes; a release that waited on it would hold the
    # finished cast's slot as long.
    @staticmethod
    async def test_a_release_does_not_wait_on_another_cast_s_prepare():
        trees = _Trees("/pool/1", "/pool/2")
        circle, _, spawn = _circle(_Limits(processes=2), trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        trees.preparing = asyncio.get_running_loop().create_future()
        await _asked_for_a_tree(circle, spawn, "c2")

        spawn.exit("c1")
        await _settled()

        assert trees.prepared[-1] == ("/pool/2", "make venv")
        assert not trees.preparing.done()
        assert trees.released == ["/pool/1"]
        trees.preparing.set_result(None)

    # The cast never ran, so nothing holds its tree or its slot.
    @staticmethod
    async def test_a_spawn_that_raises_fails_the_cast_and_frees_tree_and_slot():
        trees = _Trees("/pool/1")
        circle, hub, spawn = _circle(_Limits(processes=1), trees)
        spawn.raising = OSError("mark not written")
        circle.enqueue(_hello("c1", worktree=True))
        circle.enqueue(_hello("c2", worktree=True))
        await _settled()

        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == "mark not written"
        assert trees.released == ["/pool/1"]
        assert spawn.spawned == ["c1", "c2"]
        assert spawn.trees == ["/pool/1", "/pool/1"]

    @staticmethod
    async def test_a_tree_left_dirty_is_reported_against_its_cast():
        trees = _Trees("/pool/1")
        trees.blocked["/pool/1"] = "uncommitted changes"
        said: list[str] = []
        circle, hub, spawn = _circle(_Limits(), trees, said)
        await _asked_for_a_tree(circle, spawn, "c1")
        hub.apply(_hello("c1"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))

        spawn.exit("c1")
        await _settled()

        assert hub.casts["c1"].blocked == TreeBlocked(
            cast_id="c1", path="/pool/1", reason="uncommitted changes"
        )
        assert not trees.free
        assert said == ["/pool/1 is blocked after cast c1: uncommitted changes"]

    @staticmethod
    async def test_a_cast_that_dies_before_its_hello_in_a_dirty_tree_says_why():
        trees = _Trees("/pool/1")
        trees.blocked["/pool/1"] = "uncommitted changes"
        circle, hub, spawn = _circle(_Limits(), trees)
        await _asked_for_a_tree(circle, spawn, "c1")

        spawn.exit("c1", code=1, said="boom")
        await _settled()

        assert hub.casts["c1"].status == "error"
        assert hub.casts["c1"].detail == "exited 1 before its hello: boom"

    @staticmethod
    async def test_a_lease_that_fails_gives_its_slot_back():
        trees = _Trees()
        trees.leasing = asyncio.get_running_loop().create_future()
        trees.leasing.set_exception(TreeError("every tree is blocked"))
        circle, _, spawn = _circle(_Limits(processes=1), trees)
        await _asked_for_a_tree(circle, spawn, "c1")

        circle.enqueue(_hello("c2"))
        await _settled()

        assert spawn.spawned == ["c1", "c2"]

    # Back at the head of the line it waited in, not behind a cast that queued
    # while it was looking for a tree.
    @staticmethod
    async def test_a_cast_with_no_free_tree_goes_first_once_one_is_free():
        trees = _Trees("/pool/1")
        limits = _Limits(processes=2)
        circle, _, spawn = _circle(limits, trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        circle.enqueue(_hello("c2"))
        circle.enqueue(_hello("c3"))
        await _settled()
        spawn.exit("c2", code=NEEDS_TREE)
        await _settled()
        limits.slots = 1

        spawn.exit("c1")
        await _settled()

        assert spawn.spawned[-1] == "c2"
        assert spawn.trees[-1] == "/pool/1"

    @staticmethod
    async def test_projects_lease_without_waiting_on_each_other():
        trees = _Trees("/pool/1", "/pool/2")
        trees.leasing = asyncio.get_running_loop().create_future()
        circle, _, spawn = _circle(_Limits(), trees)
        circle.enqueue(_hello("c1", project="/one/.git"))
        circle.enqueue(_hello("c2", project="/two/.git"))
        await _settled()

        spawn.exit("c1", code=NEEDS_TREE)
        spawn.exit("c2", code=NEEDS_TREE)
        await _settled()

        assert [lease["project"] for lease in trees.leases] == [
            "/one/.git",
            "/two/.git",
        ]
        trees.leasing.set_result(None)

    @staticmethod
    async def test_a_release_waits_for_a_lease_in_its_project():
        trees = _Trees("/pool/1", "/pool/2")
        circle, _, spawn = _circle(_Limits(processes=2), trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        trees.leasing = asyncio.get_running_loop().create_future()
        circle.enqueue(_hello("c2"))
        await _settled()
        spawn.exit("c2", code=NEEDS_TREE)
        await _settled()

        spawn.exit("c1")
        await _settled()
        assert not trees.released

        trees.leasing.set_result(None)
        await _settled()
        assert trees.released == ["/pool/1"]

    @staticmethod
    async def test_a_failed_prepare_waits_for_a_lease_in_its_project():
        trees = _Trees("/pool/1", "/pool/2")
        trees.preparing = asyncio.get_running_loop().create_future()
        circle, hub, spawn = _circle(_Limits(processes=2), trees)
        await _asked_for_a_tree(circle, spawn, "c1")
        trees.leasing = asyncio.get_running_loop().create_future()
        circle.enqueue(_hello("c2"))
        await _settled()
        spawn.exit("c2", code=NEEDS_TREE)
        await _settled()

        trees.preparing.set_exception(TreeError("prepare exited 1"))
        await _settled()
        assert hub.casts["c1"].status == "queued"

        trees.leasing.set_result(None)
        await _settled()
        assert hub.casts["c1"].status == "error"


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


def _awaits(parent: str, child: str, *, request_id: str = "w1") -> AwaitRequested:
    return AwaitRequested(cast_id=parent, request_id=request_id, child=child)


def _running(hub: Hub, cast_id: str, *, root: str = "/proj") -> _Peer:
    peer = _Peer()
    hub.apply(_hello(cast_id, root=root))
    hub.open_cast(cast_id, peer)
    return peer


# What the daemon does with what a cast says of an await: the hub has it first.
def _said(circle: Circle, hub: Hub, message: AwaitRequested | AwaitWithdrawn) -> None:
    hub.apply(message)
    circle.wake()


@pytest.mark.asyncio
class TestAwaits:
    @staticmethod
    async def test_an_awaiting_parent_gives_its_slot_to_the_child():
        circle, hub, spawn = _circle(_Limits(processes=1))
        _running(hub, "parent")
        circle.enqueue(_hello("child"))
        await _settled()
        assert not spawn.spawned

        _said(circle, hub, _awaits("parent", "child"))
        await _settled()

        assert spawn.spawned == ["child"]
        assert list(hub.casts["parent"].on_children) == ["w1"]

    @staticmethod
    async def test_the_parent_comes_back_ahead_of_the_queue_with_the_result():
        record = RunRecord(hello=_hello("child"), status="ok", result={"n": 1})
        circle, hub, spawn = _circle(_Limits(processes=1), records={"child": record})
        peer = _running(hub, "parent")
        circle.enqueue(_hello("child"))
        circle.enqueue(_hello("later"))
        _said(circle, hub, _awaits("parent", "child"))
        await _settled()
        hub.apply(_hello("child"))
        hub.apply(CastGoodbye(cast_id="child", status="ok", result={"n": 1}))
        circle.wake()

        spawn.exit("child")
        await _settled()

        ended = AwaitEnded(
            cast_id="parent",
            request_id="w1",
            child="child",
            status="ok",
            result={"n": 1},
        )
        assert peer.sent == [ended]
        assert hub.casts["parent"].on_children == {}
        assert spawn.spawned == ["child"]
        assert hub.casts["later"].status == "queued"

    @staticmethod
    async def test_a_child_that_ended_before_the_await_answers_at_once():
        record = RunRecord(hello=_hello("child"), status="error", detail="boom")
        circle, hub, _ = _circle(_Limits(processes=1), records={"child": record})
        peer = _running(hub, "parent")

        _said(circle, hub, _awaits("parent", "child"))

        assert peer.sent == [
            AwaitEnded(
                cast_id="parent",
                request_id="w1",
                child="child",
                status="error",
                detail="boom",
            )
        ]

    @staticmethod
    async def test_a_child_nobody_has_heard_of_ended_in_error():
        circle, hub, _ = _circle(_Limits(processes=1))
        peer = _running(hub, "parent")

        _said(circle, hub, _awaits("parent", "ghost"))

        assert peer.sent == [
            AwaitEnded(
                cast_id="parent",
                request_id="w1",
                child="ghost",
                status="error",
                detail="no cast ghost",
            )
        ]

    # A reattach says every open await again.
    @staticmethod
    async def test_an_await_said_twice_is_answered_once():
        record = RunRecord(hello=_hello("child"), status="ok")
        circle, hub, spawn = _circle(_Limits(processes=1), records={"child": record})
        peer = _running(hub, "parent")
        circle.enqueue(_hello("child"))
        _said(circle, hub, _awaits("parent", "child"))
        _said(circle, hub, _awaits("parent", "child"))
        await _settled()
        hub.apply(_hello("child"))
        hub.apply(CastGoodbye(cast_id="child", status="ok"))
        spawn.exit("child")
        await _settled()

        circle.wake()

        assert len(peer.sent) == 1

    @staticmethod
    async def test_a_withdrawn_await_takes_its_slot_back():
        circle, hub, spawn = _circle(_Limits(processes=1))
        _running(hub, "parent")
        circle.enqueue(_hello("child"))
        _said(circle, hub, _awaits("parent", "child"))
        await _settled()

        _said(circle, hub, AwaitWithdrawn(cast_id="parent", request_id="w1"))
        circle.enqueue(_hello("later"))
        await _settled()

        assert spawn.spawned == ["child"]
        assert hub.casts["later"].status == "queued"

    @staticmethod
    async def test_a_parent_that_ends_stops_awaiting():
        circle, hub, spawn = _circle(_Limits(processes=1))
        peer = _running(hub, "parent")
        circle.enqueue(_hello("child"))
        _said(circle, hub, _awaits("parent", "child"))
        await _settled()
        hub.apply(CastGoodbye(cast_id="parent", status="error"))
        circle.wake()
        hub.apply(_hello("child"))
        hub.apply(CastGoodbye(cast_id="child", status="ok"))
        spawn.exit("child")
        await _settled()

        circle.wake()

        assert spawn.spawned == ["child"]
        assert not peer.sent

    @staticmethod
    async def test_a_child_that_says_it_needs_a_tree_is_never_probed():
        trees = _Trees("/pool/1")
        circle, _, spawn = _circle(_Limits(), trees)

        circle.enqueue(_hello("child", worktree=True))
        await _settled()

        assert spawn.trees == ["/pool/1"]

    @staticmethod
    async def test_a_child_that_dies_before_its_hello_wakes_its_parent():
        circle, hub, spawn = _circle(_Limits(processes=1))
        peer = _running(hub, "parent")
        circle.enqueue(_hello("child"))
        _said(circle, hub, _awaits("parent", "child"))
        await _settled()

        spawn.exit("child", code=2, said="no ritual named 'nap'")
        await _settled()

        assert peer.sent == [
            AwaitEnded(
                cast_id="parent",
                request_id="w1",
                child="child",
                status="error",
                detail="exited 2 before its hello: no ritual named 'nap'",
            )
        ]

    # Each parent stands in a tree and awaits a child that wants one: once both
    # wait, the next lease sees nothing will free, and fails rather than waits.
    # Its parent carries on, ends, and frees the tree the other child needs.
    @staticmethod
    async def test_parents_holding_every_tree_for_children_that_need_one_fail_one():
        trees = _Trees()
        circle, hub, spawn = _circle(_Limits(processes=4), trees)
        _running(hub, "a", root="/pool/1")
        _running(hub, "b", root="/pool/2")
        for parent, child in (("a", "a1"), ("b", "b1")):
            circle.enqueue(_hello(child, worktree=True))
            await _settled()
            _said(circle, hub, _awaits(parent, child, request_id=parent))
            await _settled()

        assert sorted(hub.casts[child].status for child in ("a1", "b1")) == [
            "error",
            "queued",
        ]
        failed = next(hub.casts[c] for c in ("a1", "b1") if hub.casts[c].detail)
        assert failed.detail == (
            "every tree is blocked or held by a cast awaiting one that needs a tree:"
            " /pool/1, /pool/2"
        )
        assert not spawn.spawned

    # Said by a cast the hub never opened: there is nobody to come back.
    @staticmethod
    async def test_an_await_from_a_cast_nobody_knows_is_dropped():
        circle, hub, spawn = _circle(_Limits(processes=1))

        _said(circle, hub, _awaits("stranger", "ghost"))
        circle.enqueue(_hello("later"))
        await _settled()

        assert spawn.spawned == ["later"]
        assert "stranger" not in hub.casts

    # After a restart the child may not have reattached yet: its record says
    # running, and that is not an ending.
    @staticmethod
    async def test_a_child_whose_record_says_running_is_still_awaited():
        record = RunRecord(hello=_hello("child"), status="running")
        circle, hub, _ = _circle(_Limits(processes=1), records={"child": record})
        peer = _running(hub, "parent")

        _said(circle, hub, _awaits("parent", "child"))

        assert not peer.sent

    # The goodbye's record could not be written, so the record still says
    # running: the view has ended all the same.
    @staticmethod
    async def test_a_child_whose_view_ended_is_not_awaited_on_a_stale_record():
        record = RunRecord(hello=_hello("child"), status="running")
        circle, hub, _ = _circle(_Limits(processes=1), records={"child": record})
        peer = _running(hub, "parent")
        hub.apply(_hello("child"))
        hub.apply(CastGoodbye(cast_id="child", status="error", detail="boom"))

        _said(circle, hub, _awaits("parent", "child"))

        assert peer.sent == [
            AwaitEnded(
                cast_id="parent",
                request_id="w1",
                child="child",
                status="error",
                detail="boom",
            )
        ]

    # The parent began awaiting while its child's lease was out: what is stuck
    # is read once the lease is back, so the child fails rather than waits.
    @staticmethod
    async def test_an_await_that_lands_mid_lease_counts():
        trees = _Trees()
        trees.leasing = asyncio.get_running_loop().create_future()
        circle, hub, _ = _circle(_Limits(processes=4), trees)
        _running(hub, "parent", root="/pool/1")
        circle.enqueue(_hello("child", worktree=True))
        await _settled()

        _said(circle, hub, _awaits("parent", "child"))
        trees.leasing.set_result(None)
        await _settled()

        assert len(trees.leases) == 1
        assert hub.casts["child"].status == "error"
        assert hub.casts["child"].detail == (
            "every tree is blocked or held by a cast awaiting one that needs a tree:"
            " /pool/1"
        )
