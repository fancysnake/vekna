import asyncio
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


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


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
        await _settle()

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

        await _settle()
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
        for _ in range(50):
            await asyncio.sleep(0.01)
            if link.attached:
                break
        await _settle()

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

    @staticmethod
    async def test_a_reattach_replaces_what_the_daemon_held(socket_path: Path):
        daemon = _Daemon()
        await daemon.start(socket_path)
        link = DaemonLink(socket_path=socket_path, hello=_hello())
        await link.attach(backlog=[to_wire(_began("r1"), cast_id=_CAST)])
        await _settle()

        await link.attach(backlog=[to_wire(_began("r2"), cast_id=_CAST)])
        await _settle()

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
        await _settle()
        waiting = list(daemon.hub.casts[_CAST].waiting.values())
        renderer.released.set()
        answer = await asking
        await _settle()

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
        await _settle()

        daemon = _Daemon()
        await daemon.start(socket_path)
        await link.attach(backlog=channel.open_prompts())
        await _settle()

        assert [
            message.prompt for message in daemon.hub.casts[_CAST].waiting.values()
        ] == ["ok?"]
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
