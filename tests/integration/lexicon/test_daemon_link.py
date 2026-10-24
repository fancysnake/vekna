import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import pytest
from pydantic import BaseModel

from vekna.lexicon._links.daemon import (
    DaemonLink,
    LinkQueue,
    TeeChannel,
    ThrottledFocus,
    to_wire,
)
from vekna.lexicon._pacts import (
    AskFn,
    CastEnded,
    CodingCall,
    CodingFocusProtocol,
    Done,
    FocusReply,
    GateFn,
    MediumBoundaryError,
    NoComponents,
    NoDaemonError,
    RiteBegan,
    RiteEnded,
    RiteStreamed,
    Ritual,
    RitualDefinitionError,
    RitualError,
)
from vekna.links.socket_server import Serving, serve
from vekna.mills.hub import Hub
from vekna.wire import (
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CastMessage,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    DecideResolved,
    EnqueueAccepted,
    EnqueueRefused,
    EnqueueRequested,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_CAST = "c1"
_PATIENCE = 200
_TICK = 0.01
_HeardT = TypeVar("_HeardT")


def _hello() -> CastHello:
    return CastHello(
        cast_id=_CAST,
        project_root="/proj",
        project="/proj/.git",
        ritual="fix_demo",
        components={"bound": 3},
        started_at=_WHEN,
    )


def _began(rite_id: str = "r1") -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id,
        parent_id=None,
        name="run_tests",
        category="step",
        started_at=_WHEN,
    )


# Socket work lands on the daemon's own turn of the event loop, so a test that
# has written waits for what it wrote to arrive rather than for a fixed number
# of turns — which is the same wait everywhere but flaky under load.
async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s waiting for the daemon to catch up"
    raise AssertionError(msg)


# Only where the assertion is that nothing arrived: there is no state to wait
# for, so what is left is to give it the chance and look.
async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


# The link's read of the socket, which is the task a closed link must not leave
# behind: it waits on an EOF that the daemon has no reason to send.
def _watchers() -> list[asyncio.Task[None]]:
    return [
        task
        for task in asyncio.all_tasks()
        if task.get_coro().__qualname__.endswith("_watch")
    ]


def _waiting(daemon: "_Daemon") -> list[WireMessage]:
    view = daemon.hub.casts.get(_CAST)
    return [] if view is None else list(view.waiting.values())


class _Daemon:
    def __init__(self, hub: Hub | None = None) -> None:
        self.hub = hub if hub is not None else Hub()
        self.server: Serving | None = None

    async def start(self, path: Path) -> None:
        self.server = await serve(path=path, routes=self.hub)

    async def stop(self) -> None:
        assert self.server is not None
        await self.server.close()
        self.server = None


class _Renderer:
    def __init__(self, answer: str = "yes") -> None:
        self.answer = answer
        self.asked: list[str] = []
        self.released = asyncio.Event()

    async def decide(
        self, *, prompt: str, options: object = None, free: bool = False
    ) -> str:
        del options, free
        self.asked.append(prompt)
        await self.released.wait()
        return self.answer


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path) -> Path:
    return tmp_path / "vekna.sock"


@pytest.mark.asyncio
class TestAttaching:
    @staticmethod
    async def test_a_cast_announces_itself_and_what_it_does(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())

        assert await link.attach()
        link.send(to_wire(_began(), cast_id=_CAST))
        await link.close(status="ok")
        await _eventually(lambda: daemon.hub.casts.get(_CAST) is not None)
        await _eventually(lambda: daemon.hub.casts[_CAST].status == "ok")

        view = daemon.hub.casts[_CAST]
        assert view.hello.ritual == "fix_demo"
        assert view.rites["r1"].started.name == "run_tests"
        assert view.status == "ok"
        await daemon.stop()

    @staticmethod
    async def test_with_no_daemon_there_is_nothing_to_attach_to(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())

        assert not await link.attach()
        # The cast carries on regardless; sending is what a detached link
        # quietly does nothing about.
        link.send(to_wire(_began(), cast_id=_CAST))

        assert not link.attached

    @staticmethod
    async def test_a_daemon_that_goes_away_leaves_the_cast_running(socket_path: Path):
        async def hang_up(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            del reader
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(hang_up, path=str(socket_path))
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()

        await _eventually(lambda: not link.attached)
        # The cast carries on; the send is what a link with nobody at the other
        # end quietly does nothing about.
        link.send(to_wire(_began(), cast_id=_CAST))

        assert not link.attached
        server.close()

    @staticmethod
    async def test_a_daemon_raised_mid_cast_is_told_the_whole_cast(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        assert not await link.attach()
        backlog: list[WireMessage] = [
            to_wire(_began(), cast_id=_CAST),
            to_wire(RiteStreamed("r1", "one"), cast_id=_CAST),
        ]
        watcher = asyncio.create_task(link.keep_attached(lambda: backlog, every=0.01))

        daemon = _Daemon()
        await daemon.start(socket_path)
        await _eventually(lambda: bool(daemon.hub.casts))
        await _eventually(lambda: bool(daemon.hub.casts[_CAST].rites))

        view = daemon.hub.casts[_CAST]
        assert list(view.rites["r1"].deltas) == ["one"]
        watcher.cancel()
        await daemon.stop()

    # The probe is a probe, not a reconnector: an attached link is left alone.
    @staticmethod
    async def test_an_attached_link_is_not_attached_again(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach(backlog=lambda: [to_wire(_began("r1"), cast_id=_CAST)])
        probing = asyncio.create_task(link.keep_attached(list, every=0.01))

        await asyncio.sleep(0.05)

        assert link.attached
        assert list(daemon.hub.casts[_CAST].rites) == ["r1"]
        probing.cancel()
        await daemon.stop()

    @staticmethod
    async def test_the_probe_stops_when_the_cast_is_over(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        probing = asyncio.create_task(link.keep_attached(list, every=0.01))
        await asyncio.sleep(0.02)

        await link.close(status="ok")

        await asyncio.wait_for(probing, timeout=1)
        assert probing.done()

    # `close` can land while the probe is inside `attach`, and a link that
    # attached after its own goodbye holds a socket the daemon never hears
    # anything more on.
    @staticmethod
    async def test_a_link_that_has_closed_does_not_attach(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.close(status="ok")

        attached = await link.attach()
        await _settle()

        assert not attached
        assert not link.attached
        assert not daemon.hub.casts
        await daemon.stop()

    @staticmethod
    async def test_closing_takes_the_watcher_with_it(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        await _eventually(lambda: bool(_watchers()))

        await link.close(status="ok")
        await _eventually(lambda: not _watchers())

        assert not _watchers()
        await daemon.stop()

    # The path `keep_attached` exists for: the daemon goes, the watcher sees the
    # EOF, and the probe puts the cast back on a replacement — which is told the
    # whole cast, not the half that happened after it started.
    @staticmethod
    async def test_the_probe_reattaches_after_the_daemon_really_went(socket_path: Path):
        first = _Daemon()
        await first.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach(backlog=lambda: [to_wire(_began("r1"), cast_id=_CAST)])
        await _eventually(lambda: bool(first.hub.casts))
        await first.stop()
        await _eventually(lambda: not link.attached)

        second = _Daemon()
        await second.start(socket_path)
        probing = asyncio.create_task(
            link.keep_attached(
                lambda: [to_wire(_began("r2"), cast_id=_CAST)], every=0.01
            )
        )
        await _eventually(lambda: bool(second.hub.casts))

        assert link.attached
        assert list(second.hub.casts[_CAST].rites) == ["r2"]
        probing.cancel()
        await second.stop()

    @staticmethod
    async def test_a_reattach_replaces_what_the_daemon_held(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach(backlog=lambda: [to_wire(_began("r1"), cast_id=_CAST)])
        await _eventually(lambda: bool(daemon.hub.casts))

        await link.attach(backlog=lambda: [to_wire(_began("r2"), cast_id=_CAST)])
        await _eventually(lambda: "r2" in daemon.hub.casts[_CAST].rites)

        assert list(daemon.hub.casts[_CAST].rites) == ["r2"]
        await daemon.stop()


@pytest.mark.asyncio
class TestPrompts:
    @staticmethod
    async def test_the_daemon_sees_a_prompt_rise_and_fall(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        renderer = _Renderer()
        channel = TeeChannel(
            inner=renderer, link=link, cast_id=_CAST, rite_id=lambda: "r1"
        )

        asking = asyncio.create_task(channel.decide(prompt="ok?"))
        await _eventually(lambda: bool(_waiting(daemon)))
        waiting = _waiting(daemon)
        renderer.released.set()
        answer = await asking
        await _eventually(lambda: not _waiting(daemon))

        assert renderer.asked == ["ok?"]
        assert answer == "yes"
        assert [message.prompt for message in waiting] == ["ok?"]
        assert not daemon.hub.casts[_CAST].waiting
        await daemon.stop()

    @staticmethod
    async def test_a_cancelled_prompt_is_withdrawn_from_the_daemon(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        channel = TeeChannel(
            inner=_Renderer(), link=link, cast_id=_CAST, rite_id=lambda: "r1"
        )

        asking = asyncio.create_task(channel.decide(prompt="ok?"))
        await _eventually(lambda: bool(_waiting(daemon)))
        asking.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asking
        await _eventually(lambda: not _waiting(daemon))

        assert not channel.open_prompts()
        await daemon.stop()

    @staticmethod
    async def test_a_prompt_still_open_is_replayed_to_a_daemon_that_arrives(
        socket_path: Path,
    ):
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        renderer = _Renderer()
        channel = TeeChannel(
            inner=renderer, link=link, cast_id=_CAST, rite_id=lambda: "r1"
        )
        asking = asyncio.create_task(channel.decide(prompt="ok?"))
        await _eventually(lambda: bool(renderer.asked))

        daemon = _Daemon()
        await daemon.start(socket_path)
        await link.attach(backlog=channel.open_prompts)
        await _eventually(lambda: bool(_waiting(daemon)))

        assert [message.prompt for message in _waiting(daemon)] == ["ok?"]
        renderer.released.set()
        await asking
        await daemon.stop()

    # The withdrawal is sent while the link is still connecting, so it is
    # dropped: only a backlog read after the connect leaves the prompt out.
    @staticmethod
    async def test_a_prompt_withdrawn_mid_connect_is_not_replayed(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        renderer = _Renderer()
        channel = TeeChannel(
            inner=renderer, link=link, cast_id=_CAST, rite_id=lambda: "r1"
        )
        asking = asyncio.create_task(channel.decide(prompt="ok?"))
        await _eventually(lambda: bool(renderer.asked))

        attaching = asyncio.create_task(link.attach(backlog=channel.open_prompts))
        asking.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asking
        assert await attaching
        await _eventually(lambda: _CAST in daemon.hub.casts)
        await _settle()

        assert not _waiting(daemon)
        await daemon.stop()

    @staticmethod
    async def test_a_prompt_with_no_daemon_is_answered_the_same_way(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        renderer = _Renderer(answer="no")
        channel = TeeChannel(
            inner=renderer, link=link, cast_id=_CAST, rite_id=lambda: "r1"
        )
        renderer.released.set()

        answer = await channel.decide(prompt="ok?", options=["yes", "no"])

        assert answer == "no"
        assert not channel.open_prompts()


class TestProjection:
    @staticmethod
    def test_a_rite_beginning_becomes_a_rite_started():
        message = to_wire(_began(), cast_id=_CAST)

        assert message.kind == "rite_started"
        assert message.cast_id == _CAST

    @staticmethod
    def test_output_becomes_a_delta():
        message = to_wire(RiteStreamed("r1", "one"), cast_id=_CAST)

        assert message.kind == "rite_delta"

    @staticmethod
    def test_an_ending_carries_its_status_and_result():
        message = to_wire(
            RiteEnded(rite_id="r1", status="error", result={"x": 1}, finished_at=_WHEN),
            cast_id=_CAST,
        )

        assert message.kind == "rite_finished"
        assert message.status == "error"
        assert message.result == {"x": 1}


# A hub that keeps the slot traffic the real daemon hands its circle, so a test
# can grant by hand.
class _Slots(Hub):
    def __init__(self) -> None:
        super().__init__()
        self.slots: list[CastMessage] = []

    def apply(self, message: CastMessage) -> None:
        if isinstance(message, CodingSlotRequested | CodingSlotReleased):
            self.slots.append(message)
        else:
            super().apply(message)


def _asked_id(daemon: _Daemon) -> str:
    return _waiting(daemon)[0].request_id


@pytest.mark.asyncio
class TestAnsweredOverTheWire:
    @staticmethod
    async def test_a_spawned_cast_takes_the_answer_a_surface_sends(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        tee = TeeChannel(inner=None, link=link, cast_id=_CAST, rite_id=lambda: None)
        asking = asyncio.create_task(tee.decide(prompt="go?", options=["go", "stop"]))
        await _eventually(lambda: bool(_waiting(daemon)))

        daemon.hub.answer(
            DecideResolved(cast_id=_CAST, request_id=_asked_id(daemon), answer="go")
        )

        assert await asyncio.wait_for(asking, timeout=2) == "go"
        await _eventually(lambda: not _waiting(daemon))
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_an_answer_the_prompt_does_not_offer_leaves_it_open(
        socket_path: Path,
    ):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        tee = TeeChannel(inner=None, link=link, cast_id=_CAST, rite_id=lambda: None)
        asking = asyncio.create_task(tee.decide(prompt="go?", options=["go", "stop"]))
        await _eventually(lambda: bool(_waiting(daemon)))
        request_id = _asked_id(daemon)

        daemon.hub.answer(
            DecideResolved(cast_id=_CAST, request_id=request_id, answer="maybe")
        )
        await _settle()
        assert not asking.done()

        daemon.hub.answer(
            DecideResolved(cast_id=_CAST, request_id=request_id, answer="stop")
        )
        assert await asyncio.wait_for(asking, timeout=2) == "stop"
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_an_answer_to_a_prompt_never_asked_is_dropped(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        tee = TeeChannel(inner=None, link=link, cast_id=_CAST, rite_id=lambda: None)
        asking = asyncio.create_task(tee.decide(prompt="go?", options=["go", "stop"]))
        await _eventually(lambda: bool(_waiting(daemon)))

        daemon.hub.tell(
            _CAST, DecideResolved(cast_id=_CAST, request_id="never", answer="go")
        )
        await _settle()
        assert not asking.done()

        daemon.hub.answer(
            DecideResolved(cast_id=_CAST, request_id=_asked_id(daemon), answer="stop")
        )
        assert await asyncio.wait_for(asking, timeout=2) == "stop"
        await link.close(status="ok")
        await daemon.stop()

    # Two answers in one read: the first settles the prompt before the cast
    # resumes to stop listening, and the second must not settle it again.
    @staticmethod
    async def test_the_first_answer_stands_over_a_second_in_the_same_read(
        socket_path: Path,
    ):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        tee = TeeChannel(inner=None, link=link, cast_id=_CAST, rite_id=lambda: None)
        asking = asyncio.create_task(tee.decide(prompt="go?", options=["go", "stop"]))
        await _eventually(lambda: bool(_waiting(daemon)))
        request_id = _asked_id(daemon)

        for answer in ("go", "stop"):
            daemon.hub.tell(
                _CAST,
                DecideResolved(cast_id=_CAST, request_id=request_id, answer=answer),
            )

        assert await asyncio.wait_for(asking, timeout=2) == "go"
        await link.close(status="ok")
        await daemon.stop()


@pytest.mark.asyncio
class TestCodingSlots:
    @staticmethod
    async def test_the_call_waits_for_its_grant_and_says_when_done(socket_path: Path):
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        entered = asyncio.Event()

        async def call() -> None:
            async with link.coding():
                entered.set()

        calling = asyncio.create_task(call())
        await _eventually(lambda: bool(hub.slots))
        await _settle()
        assert not entered.is_set()

        asked = hub.slots[0]
        assert isinstance(asked, CodingSlotRequested)
        hub.tell(_CAST, CodingSlotGranted(cast_id=_CAST, request_id=asked.request_id))
        await asyncio.wait_for(calling, timeout=2)

        released = CodingSlotReleased(cast_id=_CAST, request_id=asked.request_id)
        await _eventually(lambda: hub.slots == [asked, released])
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_with_no_daemon_there_is_no_limit_to_wait_on(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())

        async with asyncio.timeout(2), link.coding():
            pass

    # A dying daemon must not strand a cast at an agent call.
    @staticmethod
    async def test_a_daemon_that_goes_lets_the_wait_go(socket_path: Path):
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()

        async def call() -> None:
            async with link.coding():
                pass

        calling = asyncio.create_task(call())
        await _eventually(lambda: bool(hub.slots))

        await daemon.stop()

        await asyncio.wait_for(calling, timeout=2)
        await link.close(status="ok")

    # A daemon started mid-session counts the slot already held.
    @staticmethod
    async def test_a_slot_held_is_asked_for_again_on_the_next_attach(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        released = asyncio.Event()

        async def call() -> None:
            async with link.coding():
                await released.wait()

        calling = asyncio.create_task(call())
        await _settle()
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)

        await link.attach()

        await _eventually(lambda: bool(hub.slots))
        assert isinstance(hub.slots[0], CodingSlotRequested)
        released.set()
        await asyncio.wait_for(calling, timeout=2)
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_a_grant_for_a_slot_never_asked_for_is_dropped(socket_path: Path):
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        entered = asyncio.Event()

        async def call() -> None:
            async with link.coding():
                entered.set()

        calling = asyncio.create_task(call())
        await _eventually(lambda: bool(hub.slots))
        asked = hub.slots[0]
        assert isinstance(asked, CodingSlotRequested)

        hub.tell(_CAST, CodingSlotGranted(cast_id=_CAST, request_id="never"))
        await _settle()
        assert not entered.is_set()

        hub.tell(_CAST, CodingSlotGranted(cast_id=_CAST, request_id=asked.request_id))
        await asyncio.wait_for(calling, timeout=2)
        await link.close(status="ok")
        await daemon.stop()

    # A slot taken with no daemon has no grant to let go, and one already
    # granted is not let go twice: both blocks run on until they end.
    @staticmethod
    async def test_a_daemon_that_goes_leaves_held_slots_held(socket_path: Path):
        released = asyncio.Event()
        link = DaemonLink(socket_path=socket_path, hello=_hello())

        async def call() -> None:
            async with link.coding():
                await released.wait()

        unasked = asyncio.create_task(call())
        await _settle()
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        await link.attach()
        granted = asyncio.create_task(call())
        await _eventually(lambda: len(hub.slots) > 1)
        asked = hub.slots[1]
        assert isinstance(asked, CodingSlotRequested)
        hub.tell(_CAST, CodingSlotGranted(cast_id=_CAST, request_id=asked.request_id))
        await _settle()

        await daemon.stop()
        await _eventually(lambda: not link.attached)

        assert not unasked.done()
        assert not granted.done()
        released.set()
        await asyncio.wait_for(asyncio.gather(unasked, granted), timeout=2)
        await link.close(status="ok")


# Says what slot traffic the daemon had seen by the time the agent ran.
class _Agent(CodingFocusProtocol):
    def __init__(self, hub: _Slots) -> None:
        self._hub = hub
        self.seen: list[CastMessage] = []

    async def run(
        self,
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        del call, on_delta, gate, ask
        self.seen = list(self._hub.slots)
        return FocusReply(text="done")


@pytest.mark.asyncio
class TestThrottledFocus:
    @staticmethod
    async def test_the_agent_runs_inside_a_granted_slot(socket_path: Path):
        hub = _Slots()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach()
        agent = _Agent(hub)
        call = CodingCall(
            prompt="fix it",
            model=None,
            system=None,
            cwd=None,
            output_schema=None,
            focus_options=None,
        )

        running = asyncio.create_task(
            ThrottledFocus(inner=agent, link=link).run(
                call, on_delta=print, gate=None, ask=_never
            )
        )
        await _eventually(lambda: bool(hub.slots))
        asked = hub.slots[0]
        assert isinstance(asked, CodingSlotRequested)
        hub.tell(_CAST, CodingSlotGranted(cast_id=_CAST, request_id=asked.request_id))

        assert await asyncio.wait_for(running, timeout=2) == FocusReply(text="done")
        assert agent.seen == [asked]
        released = CodingSlotReleased(cast_id=_CAST, request_id=asked.request_id)
        await _eventually(lambda: hub.slots == [asked, released])
        await link.close(status="ok")
        await daemon.stop()


def _never(question: str, options: Sequence[str] | None) -> Awaitable[str]:
    msg = f"the agent was not meant to ask {question!r} ({options!r})"
    raise AssertionError(msg)


class _Queue(Hub):
    def __init__(self) -> None:
        super().__init__()
        self.heard: list[CastMessage] = []

    def apply(self, message: CastMessage) -> None:
        if isinstance(
            message, EnqueueRequested | AwaitRequested | AwaitWithdrawn | CastGoodbye
        ):
            self.heard.append(message)
        super().apply(message)


class _Nap(BaseModel):
    minutes: int


def _nothing(_: BaseModel) -> Awaitable[Done[None]]:
    return asyncio.sleep(0, result=Done(None))


_NAP = Ritual(
    name="tome:nap",
    components=_Nap,
    run=_nothing,
    max_steps=1,
    exits=(),
    ends=True,
    worktree=True,
)


def _nap(name: str) -> Ritual:
    if name != "nap":
        msg = f"no ritual named {name!r}"
        raise RitualDefinitionError(msg)
    return _NAP


async def _attached(socket_path: Path) -> tuple[_Queue, _Daemon, DaemonLink]:
    hub = _Queue()
    daemon = _Daemon(hub)
    await daemon.start(socket_path)
    link = DaemonLink(socket_path=socket_path, hello=_hello())
    await link.attach()
    return hub, daemon, link


def _first(heard: list[CastMessage], kind: type[_HeardT]) -> _HeardT:
    return next(message for message in heard if isinstance(message, kind))


@pytest.mark.asyncio
class TestQueue:
    @staticmethod
    async def test_a_child_is_queued_by_the_name_that_means_one_ritual(
        socket_path: Path,
    ):
        hub, daemon, link = await _attached(socket_path)
        queue = LinkQueue(link=link, ritual=_nap)

        enqueuing = asyncio.create_task(
            queue.enqueue(ritual="nap", components=_Nap(minutes=5))
        )
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, EnqueueRequested)
        hub.tell(_CAST, EnqueueAccepted(cast_id=_CAST, request_id=asked.request_id))

        assert await asyncio.wait_for(enqueuing, timeout=2) == asked.hello.cast_id
        child = asked.hello
        assert (child.ritual, child.components) == ("tome:nap", {"minutes": 5})
        assert (child.project_root, child.project) == ("/proj", "/proj/.git")
        assert (child.enqueued_by, child.worktree, child.wired) == (_CAST, True, True)
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_a_refusal_says_why(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        queue = LinkQueue(link=link, ritual=_nap)

        enqueuing = asyncio.create_task(
            queue.enqueue(ritual="nap", components=_Nap(minutes=5))
        )
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, EnqueueRequested)
        hub.tell(
            _CAST,
            EnqueueRefused(cast_id=_CAST, request_id=asked.request_id, reason="gone"),
        )

        with pytest.raises(RitualError, match="not queued: gone"):
            await asyncio.wait_for(enqueuing, timeout=2)
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_components_of_another_ritual_are_refused_before_the_wire(
        socket_path: Path,
    ):
        hub, daemon, link = await _attached(socket_path)
        queue = LinkQueue(link=link, ritual=_nap)

        with pytest.raises(MediumBoundaryError, match="tome:nap takes _Nap, not"):
            await queue.enqueue(ritual="nap", components=NoComponents())

        assert not [m for m in hub.heard if isinstance(m, EnqueueRequested)]
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_with_no_daemon_the_queue_is_refused(socket_path: Path):
        link = DaemonLink(socket_path=socket_path, hello=_hello())

        with pytest.raises(NoDaemonError, match="needs a daemon"):
            await link.enqueue(_hello())
        with pytest.raises(NoDaemonError, match="needs a daemon"):
            await link.await_end("c2")

    @staticmethod
    async def test_a_daemon_gone_before_it_answers_fails_the_enqueue(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        enqueuing = asyncio.create_task(link.enqueue(_hello()))
        await _eventually(lambda: bool(hub.heard))

        await daemon.stop()

        with pytest.raises(NoDaemonError, match="went away before"):
            await asyncio.wait_for(enqueuing, timeout=2)
        await link.close(status="ok")

    @staticmethod
    async def test_an_await_returns_how_the_child_ended(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)

        awaiting = asyncio.create_task(link.await_end("c2"))
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, AwaitRequested)
        ended = AwaitEnded(
            cast_id=_CAST,
            request_id=asked.request_id,
            child="c2",
            status="ok",
            result={"n": 1},
        )
        hub.tell(_CAST, ended)

        assert await asyncio.wait_for(awaiting, timeout=2) == ended
        assert asked.child == "c2"
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_a_cancelled_await_is_withdrawn(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        awaiting = asyncio.create_task(link.await_end("c2"))
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, AwaitRequested)

        awaiting.cancel()

        withdrawn = AwaitWithdrawn(cast_id=_CAST, request_id=asked.request_id)
        await _eventually(lambda: withdrawn in hub.heard)
        await link.close(status="ok")
        await daemon.stop()

    # The next daemon answers off its journal.
    @staticmethod
    async def test_an_await_outlives_the_daemon_and_is_said_again(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        awaiting = asyncio.create_task(link.await_end("c2"))
        await _eventually(lambda: bool(hub.heard))
        await daemon.stop()
        await _settle()
        assert not awaiting.done()

        hub = _Queue()
        daemon = _Daemon(hub)
        await daemon.start(socket_path)
        await link.attach()

        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, AwaitRequested)
        ended = AwaitEnded(
            cast_id=_CAST, request_id=asked.request_id, child="c2", status="error"
        )
        hub.tell(_CAST, ended)
        assert await asyncio.wait_for(awaiting, timeout=2) == ended
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_the_goodbye_carries_the_result(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)

        await link.close(status="ok", result={"n": 1})

        await _eventually(lambda: bool(hub.heard))
        assert hub.heard == [CastGoodbye(cast_id=_CAST, status="ok", result={"n": 1})]
        await daemon.stop()

    @staticmethod
    async def test_an_answer_to_an_enqueue_never_asked_is_dropped(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        enqueuing = asyncio.create_task(link.enqueue(_hello()))
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, EnqueueRequested)

        hub.tell(_CAST, EnqueueAccepted(cast_id=_CAST, request_id="never"))
        await _settle()
        assert not enqueuing.done()

        hub.tell(_CAST, EnqueueAccepted(cast_id=_CAST, request_id=asked.request_id))
        await asyncio.wait_for(enqueuing, timeout=2)
        await link.close(status="ok")
        await daemon.stop()

    @staticmethod
    async def test_the_queue_hands_the_medium_how_the_child_ended(socket_path: Path):
        hub, daemon, link = await _attached(socket_path)
        queue = LinkQueue(link=link, ritual=_nap)

        awaiting = asyncio.create_task(queue.await_end("c2"))
        await _eventually(lambda: bool(hub.heard))
        asked = _first(hub.heard, AwaitRequested)
        hub.tell(
            _CAST,
            AwaitEnded(
                cast_id=_CAST,
                request_id=asked.request_id,
                child="c2",
                status="error",
                detail="red",
            ),
        )

        assert await asyncio.wait_for(awaiting, timeout=2) == CastEnded(
            status="error", detail="red", result=None
        )
        await link.close(status="ok")
        await daemon.stop()
