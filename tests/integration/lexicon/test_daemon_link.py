import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.lexicon._links.daemon import DaemonLink, TeeChannel, to_wire
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed
from vekna.links.socket_server import Serving, serve
from vekna.mills.hub import Hub
from vekna.wire import CastHello, WireMessage

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_CAST = "c1"
_PATIENCE = 200
_TICK = 0.01


def _hello() -> CastHello:
    return CastHello(
        cast_id=_CAST,
        project_root="/proj",
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
    def __init__(self) -> None:
        self.hub = Hub()
        self.server: Serving | None = None

    async def start(self, path: Path) -> None:
        self.server = await serve(
            path=path,
            on_message=self.hub.apply,
            on_attach=self.hub.attach_surface,
            on_detach=self.hub.detach_surface,
        )

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
        await link.attach(backlog=[to_wire(_began("r1"), cast_id=_CAST)])
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
        await link.attach(backlog=[to_wire(_began("r1"), cast_id=_CAST)])
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
        await link.attach(backlog=[to_wire(_began("r1"), cast_id=_CAST)])
        await _eventually(lambda: bool(daemon.hub.casts))

        await link.attach(backlog=[to_wire(_began("r2"), cast_id=_CAST)])
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
        await link.attach(backlog=channel.open_prompts())
        await _eventually(lambda: bool(_waiting(daemon)))

        assert [message.prompt for message in _waiting(daemon)] == ["ok?"]
        renderer.released.set()
        await asking
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
