import asyncio
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from vekna.links.socket_server import Serving, alive, attach, serve
from vekna.pacts.routing import SocketPathError, Wiring
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    LichDismissRequested,
    LichFell,
    LichRose,
    LichStatus,
    LichUpdate,
    RiteDelta,
    SurfaceCommand,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

if TYPE_CHECKING:
    from vekna.pacts.routing import Surface

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_OWNER_ONLY = 0o600
_PATIENCE = 200
_TICK = 0.01
_TWO = 2
_PERMISSION_BITS = 0o777
_PAST_DEFAULT = 128 * 1024


def _hello() -> CastHello:
    return CastHello(
        cast_id="c1",
        project_root="/proj",
        ritual="fix_demo",
        components={},
        started_at=_WHEN,
    )


def _said_goodbye(daemon: "_Daemon") -> bool:
    return bool(daemon.messages) and isinstance(daemon.messages[-1], CastGoodbye)


def _rose(name: str = "hollow-vesper") -> LichRose:
    return LichRose(name=name, root="/proj", pid=4242)


# Everything the lich half of the wiring was told, kept together — one
# attribute on the daemon below rather than four.
@dataclass
class _Liches:
    risen: list[LichRose] = field(default_factory=list)
    said: list[LichUpdate] = field(default_factory=list)
    fallen: list[str] = field(default_factory=list)
    commanded: list[SurfaceCommand] = field(default_factory=list)
    # What `on_rise` answers, so a test can be about a name already taken.
    refuse: str | None = None


class _Daemon:
    def __init__(self) -> None:
        self.messages: list[WireMessage] = []
        self.attached: list[Surface] = []
        self.detached: list[Surface] = []
        self.liches = _Liches()

    async def start(self, path: Path) -> Serving:
        return await serve(path=path, wiring=self.wiring())

    # `on_message` is a parameter because one test needs a handler that raises;
    # everything else about the wiring is the same either way.
    def wiring(self, on_message: Callable[[CastMessage], None] | None = None) -> Wiring:
        return Wiring(
            on_message=self.messages.append if on_message is None else on_message,
            on_attach=self.attached.append,
            on_detach=self.detached.append,
            on_rise=self._risen,
            on_lich=self.liches.said.append,
            on_fallen=self.liches.fallen.append,
            on_command=self.liches.commanded.append,
        )

    def _risen(self, message: LichRose, station: "Surface") -> str | None:
        del station
        if self.liches.refuse is None:
            self.liches.risen.append(message)
        return self.liches.refuse


# The daemon reacts on its own turn of the event loop, so a client that has
# written and closed has not necessarily been heard yet. Waited for by what
# arrives rather than by a count of turns, which is the same wait until the
# machine is busy.
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
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path) -> Path:
    return tmp_path / "vekna.sock"


@pytest.mark.asyncio
class TestServing:
    @staticmethod
    async def test_a_cast_is_heard(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(RiteDelta(cast_id="c1", rite_id="r1", delta="x")))
        await writer.drain()
        await _eventually(lambda: len(daemon.messages) == _TWO)

        assert [message.kind for message in daemon.messages] == [
            "cast_hello",
            "rite_delta",
        ]
        await server.close()

    # A shell medium's result is everything the command printed, so a `git diff`
    # arrives as one frame past asyncio's 64KiB stream default.
    @staticmethod
    async def test_a_frame_past_the_stream_default_is_heard(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        big = RiteDelta(cast_id="c1", rite_id="r1", delta="x" * _PAST_DEFAULT)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(big))
        await writer.drain()
        await _eventually(lambda: len(daemon.messages) == _TWO)

        assert daemon.messages == [_hello(), big]
        writer.close()
        await server.close()

    @staticmethod
    async def test_the_socket_is_the_users_alone(socket_path: Path):
        server = await _Daemon().start(socket_path)

        mode = (await asyncio.to_thread(socket_path.stat)).st_mode

        assert mode & _PERMISSION_BITS == _OWNER_ONLY
        await server.close()

    @staticmethod
    async def test_a_surface_attaches_and_is_sent_to(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        reader, writer = await attach(socket_path)
        writer.write(encode_frame(SurfaceHello()))
        await writer.drain()
        await _eventually(lambda: bool(daemon.attached))
        daemon.attached[0].send(_hello())
        heard = await anext(aiter(read_frames(reader)))

        assert heard == _hello()
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_surface_leaving_is_noticed(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(SurfaceHello()))
        await writer.drain()
        await _eventually(lambda: bool(daemon.attached))

        writer.close()
        await _eventually(lambda: bool(daemon.detached))

        assert daemon.detached == daemon.attached
        await server.close()


@pytest.mark.asyncio
class TestUncleanExits:
    @staticmethod
    async def test_a_cast_that_vanishes_says_goodbye_for_itself(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        await writer.drain()
        await _eventually(lambda: bool(daemon.messages))

        writer.close()
        await _eventually(lambda: len(daemon.messages) == _TWO)

        assert daemon.messages[-1] == CastGoodbye(
            cast_id="c1",
            status="disconnected",
            detail="socket closed without a goodbye",
        )
        await server.close()

    @staticmethod
    async def test_a_cast_that_said_goodbye_is_not_said_for(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(CastGoodbye(cast_id="c1", status="ok")))
        await writer.drain()
        await _eventually(lambda: len(daemon.messages) == _TWO)

        writer.close()
        await _settle()

        assert daemon.messages[-1] == CastGoodbye(cast_id="c1", status="ok")
        await server.close()

    @staticmethod
    async def test_what_opened_as_a_surface_stays_one(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(SurfaceHello()))
        writer.write(encode_frame(_hello()))
        await writer.drain()
        await _settle()

        writer.close()
        await _settle()

        assert not daemon.messages
        assert daemon.detached == daemon.attached
        await server.close()

    @staticmethod
    async def test_a_cast_saying_hello_as_a_surface_is_still_a_cast(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(SurfaceHello()))
        writer.write(encode_frame(RiteDelta(cast_id="c1", rite_id="r1", delta="x")))
        await writer.drain()
        await _eventually(lambda: len(daemon.messages) == _TWO)

        assert [message.kind for message in daemon.messages] == [
            "cast_hello",
            "rite_delta",
        ]
        assert not daemon.attached
        writer.close()
        await server.close()

    @staticmethod
    async def test_an_os_error_out_of_the_read_loop_is_a_goodbye(socket_path: Path):
        daemon = _Daemon()

        def unwritable(message: WireMessage) -> None:
            daemon.messages.append(message)
            if isinstance(message, RiteDelta):
                raise OSError(28, "No space left on device")

        server = await serve(path=socket_path, wiring=daemon.wiring(unwritable))
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(RiteDelta(cast_id="c1", rite_id="r1", delta="x")))
        await writer.drain()
        await _eventually(lambda: _said_goodbye(daemon))

        goodbye = daemon.messages[-1]
        assert isinstance(goodbye, CastGoodbye)
        assert goodbye.detail == "connection lost: [Errno 28] No space left on device"
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_frame_for_another_cast_ends_the_connection(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(CastGoodbye(cast_id="c2", status="ok")))
        await writer.drain()
        await _eventually(lambda: _said_goodbye(daemon))

        goodbye = daemon.messages[-1]

        assert isinstance(goodbye, CastGoodbye)
        assert goodbye.cast_id == "c1"
        assert goodbye.status == "disconnected"
        assert goodbye.detail == "sent a frame for cast 'c2'"
        assert daemon.messages == [_hello(), goodbye]
        writer.close()
        await server.close()

    @staticmethod
    async def test_an_unreadable_frame_ends_one_connection_and_says_why(
        socket_path: Path,
    ):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(b'{"kind": "not_a_kind"}\n')
        await writer.drain()
        await _eventually(lambda: _said_goodbye(daemon))

        goodbye = daemon.messages[-1]

        assert isinstance(goodbye, CastGoodbye)
        assert goodbye.status == "disconnected"
        assert goodbye.detail is not None
        assert goodbye.detail.startswith("unreadable frame:")
        writer.close()
        await server.close()


@pytest.mark.asyncio
class TestBinding:
    @staticmethod
    async def test_a_second_daemon_finds_the_socket_taken(socket_path: Path):
        first = await _Daemon().start(socket_path)

        assert await alive(socket_path)
        await first.close()

    # A socket file whose server is gone, left where a killed daemon leaves it:
    # closing a `Serving` unlinks its own path, so binding over that would be
    # testing a path with nothing at it.
    @staticmethod
    async def test_a_socket_nobody_answers_is_cleared_away(socket_path: Path):
        stale = socket.socket(socket.AF_UNIX)
        try:
            stale.bind(str(socket_path))
        finally:
            stale.close()
        assert await asyncio.to_thread(socket_path.is_socket)
        assert not await alive(socket_path)

        server = await _Daemon().start(socket_path)

        assert await alive(socket_path)
        await server.close()

    @staticmethod
    async def test_a_path_held_by_something_else_says_so(socket_path: Path):
        await asyncio.to_thread(
            socket_path.write_text, "not a socket at all", encoding="utf-8"
        )

        with pytest.raises(SocketPathError, match="is not a socket"):
            await _Daemon().start(socket_path)

    @staticmethod
    async def test_nothing_listening_is_not_alive(socket_path: Path):
        assert not await alive(socket_path)


# The third kind of connection: addressed by name, sent to as well as heard
# from, and refused where one of that name already stands.
@pytest.mark.asyncio
class TestLiches:
    @staticmethod
    async def test_a_lich_rises_and_is_heard_from(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(_rose()))
        writer.write(encode_frame(LichStatus(name="hollow-vesper")))
        await writer.drain()
        await _eventually(lambda: bool(daemon.liches.said))

        assert daemon.liches.risen == [_rose()]
        assert daemon.liches.said == [LichStatus(name="hollow-vesper")]
        writer.close()
        await server.close()

    # A lich whose socket closed without a word: the daemon holds a station
    # every command would otherwise vanish into.
    @staticmethod
    async def test_a_lich_that_vanishes_is_said_to_have_fallen(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_rose()))
        await writer.drain()
        await _eventually(lambda: bool(daemon.liches.risen))

        writer.close()
        await _eventually(lambda: bool(daemon.liches.fallen))

        assert daemon.liches.fallen == ["hollow-vesper"]
        await server.close()

    @staticmethod
    async def test_a_lich_that_said_it_fell_is_not_said_for(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_rose()))
        writer.write(encode_frame(LichFell(name="hollow-vesper", reason="dismissed")))
        await writer.drain()
        await _eventually(lambda: bool(daemon.liches.said))

        writer.close()
        await _settle()

        assert not daemon.liches.fallen
        await server.close()

    # A refused rising is told by the socket closing under it — which is what
    # the lich process reads as "not the lich of that name".
    @staticmethod
    async def test_a_refused_rising_is_closed_on(socket_path: Path):
        daemon = _Daemon()
        daemon.liches.refuse = "a lich of that name is already standing"
        server = await daemon.start(socket_path)

        reader, writer = await attach(socket_path)
        writer.write(encode_frame(_rose()))
        await writer.drain()

        assert not await reader.read()
        assert not daemon.liches.fallen
        writer.close()
        await server.close()

    # A frame naming another lich is not routed, for the reason a cast's is
    # not: any process on this account could otherwise speak for a station.
    @staticmethod
    async def test_a_lich_speaking_for_another_is_not_routed(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_rose()))
        writer.write(encode_frame(LichStatus(name="ashen-quill")))
        writer.write(encode_frame(LichStatus(name="hollow-vesper")))
        await writer.drain()
        await _eventually(lambda: bool(daemon.liches.said))

        assert daemon.liches.said == [LichStatus(name="hollow-vesper")]
        writer.close()
        await server.close()

    # Nobody opens a connection with a frame only a standing lich sends.
    @staticmethod
    async def test_opening_with_a_lich_update_is_nobody(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(LichStatus(name="hollow-vesper")))
        await writer.drain()
        await _settle()

        assert not daemon.liches.risen
        assert not daemon.liches.said
        assert not daemon.messages
        writer.close()
        await server.close()

    # A surface takes orders now: what a lich needs and no more.
    @staticmethod
    async def test_a_command_from_a_surface_is_routed(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(SurfaceHello()))
        writer.write(encode_frame(LichDismissRequested(name="hollow-vesper")))
        await writer.drain()
        await _eventually(lambda: bool(daemon.liches.commanded))

        assert daemon.liches.commanded == [LichDismissRequested(name="hollow-vesper")]
        writer.close()
        await server.close()
