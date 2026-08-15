import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from vekna.links.socket_server import Serving, alive, attach, default_socket_path, serve
from vekna.pacts.routing import SocketPathError
from vekna.wire import (
    CastGoodbye,
    CastHello,
    RiteDelta,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

if TYPE_CHECKING:
    from vekna.pacts.routing import Surface

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_OWNER_ONLY = 0o600
_PERMISSION_BITS = 0o777


def _hello() -> CastHello:
    return CastHello(
        cast_id="c1",
        project_root="/proj",
        ritual="fix_demo",
        components={},
        started_at=_WHEN,
    )


class _Daemon:
    def __init__(self) -> None:
        self.messages: list[WireMessage] = []
        self.attached: list[Surface] = []
        self.detached: list[Surface] = []

    async def start(self, path: Path) -> Serving:
        return await serve(
            path=path,
            on_message=self.messages.append,
            on_attach=self.attached.append,
            on_detach=self.detached.append,
        )


# The daemon reacts on its own event loop turn, so a client that has written and
# closed has not necessarily been heard yet.
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
        await _settle()

        assert [message.kind for message in daemon.messages] == [
            "cast_hello",
            "rite_delta",
        ]
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
        await _settle()
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
        await _settle()

        writer.close()
        await _settle()

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
        await _settle()

        writer.close()
        await _settle()

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
        await _settle()

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
    async def test_an_os_error_out_of_the_read_loop_is_a_goodbye(socket_path: Path):
        daemon = _Daemon()

        def unwritable(message: WireMessage) -> None:
            daemon.messages.append(message)
            if isinstance(message, RiteDelta):
                raise OSError(28, "No space left on device")

        server = await serve(
            path=socket_path,
            on_message=unwritable,
            on_attach=daemon.attached.append,
            on_detach=daemon.detached.append,
        )
        _, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        writer.write(encode_frame(RiteDelta(cast_id="c1", rite_id="r1", delta="x")))
        await writer.drain()
        await _settle()

        goodbye = daemon.messages[-1]
        assert isinstance(goodbye, CastGoodbye)
        assert goodbye.detail == "connection lost: [Errno 28] No space left on device"
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
        await _settle()

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

    @staticmethod
    async def test_a_socket_nobody_answers_is_cleared_away(socket_path: Path):
        killed = await _Daemon().start(socket_path)
        await killed.close()
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


class TestDefaultPath:
    @staticmethod
    def test_the_environment_names_it(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("VEKNA_SOCKET", "/tmp/mine.sock")

        assert default_socket_path() == Path("/tmp/mine.sock")

    @staticmethod
    def test_otherwise_it_is_one_per_user(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("VEKNA_SOCKET", raising=False)

        assert default_socket_path().name.startswith("vekna-")
