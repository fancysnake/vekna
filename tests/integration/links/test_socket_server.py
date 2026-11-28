import asyncio
import logging
import os
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.links.socket_server import Serving, alive, attach, serve
from vekna.pacts.routing import Routes, SocketPathError, Surface
from vekna.wire import (
    VERSION,
    AdmissionRequested,
    AltarRequested,
    AltarTended,
    CastAdmitted,
    CastCancelRequested,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastQueued,
    CastRefused,
    CastRequested,
    CastSeen,
    DaemonVersion,
    DecideClaimed,
    DecideReleased,
    DecideResolved,
    HeldTree,
    RiteDelta,
    StopRequested,
    SurfaceHello,
    VersionRequested,
    VigilsRequested,
    VigilsState,
    WireMessage,
    admission_refusal,
    encode_frame,
    mark_seen,
    read_frames,
    set_vigils_paused,
    vigils_paused,
)

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
        project="/proj/.git",
        ritual="fix_demo",
        components={},
        started_at=_WHEN,
    )


def _said_goodbye(daemon: "_Daemon") -> bool:
    return bool(daemon.messages) and isinstance(daemon.messages[-1], CastGoodbye)


class _Daemon(Routes):
    def __init__(self) -> None:
        self.messages: list[WireMessage] = []
        self.attached: list[Surface] = []
        self.detached: list[Surface] = []
        self.requests: list[
            CastRequested
            | AltarRequested
            | AdmissionRequested
            | CastSeen
            | VigilsRequested
        ] = []
        # What surfaces said about prompts and casts, and which surface said it.
        self.prompted: list[
            tuple[
                Surface,
                DecideClaimed | DecideReleased | DecideResolved | CastCancelRequested,
            ]
        ] = []
        self.peers: dict[str, Surface] = {}
        self.closed: list[str] = []

    def apply(self, message: CastMessage) -> None:
        self.messages.append(message)

    def attach_surface(self, surface: Surface) -> None:
        self.attached.append(surface)

    def detach_surface(self, surface: Surface) -> None:
        self.detached.append(surface)

    def request(self, surface: Surface, request: CastRequested) -> None:
        del surface
        self.requests.append(request)

    def answer(self, surface: Surface, resolved: DecideResolved) -> None:
        self.prompted.append((surface, resolved))

    def claim(self, surface: Surface, claimed: DecideClaimed) -> None:
        self.prompted.append((surface, claimed))

    def release(self, surface: Surface, released: DecideReleased) -> None:
        self.prompted.append((surface, released))

    def cancel(self, surface: Surface, cancel: CastCancelRequested) -> None:
        self.prompted.append((surface, cancel))

    def mark(self, request: CastSeen) -> CastGoodbye | CastRefused:
        self.requests.append(request)
        return CastGoodbye(cast_id=request.cast_id, status="error", seen=request.seen)

    def vigils(self, request: VigilsRequested) -> VigilsState:
        self.requests.append(request)
        return VigilsState(paused=bool(request.pause))

    def open_cast(self, cast_id: str, peer: Surface) -> None:
        self.peers[cast_id] = peer

    def close_cast(self, cast_id: str, peer: Surface) -> None:
        del peer
        self.closed.append(cast_id)

    async def altar(self, request: AltarRequested) -> AltarTended | CastRefused:
        self.requests.append(request)
        return AltarTended(trees=[HeldTree(path=f"{request.project_root}/1")])

    async def admit(self, request: AdmissionRequested) -> CastAdmitted | CastRefused:
        self.requests.append(request)
        return CastRefused(reason="full")

    async def queue(self, request: CastRequested) -> CastQueued | CastRefused:
        self.requests.append(request)
        return CastQueued(cast_id="c1")

    async def start(self, path: Path) -> Serving:
        return await serve(path=path, routes=self)


class _Unwritable(_Daemon):
    def apply(self, message: CastMessage) -> None:
        super().apply(message)
        if isinstance(message, RiteDelta):
            raise OSError(28, "No space left on device")


def _command(pid: int) -> str:
    said = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    return said.decode().strip()


def _unreadable(_: Path, **__: object) -> bytes:
    raise ProcessLookupError


def _without_parent(_: Path, **__: object) -> str:
    return "Name:\tvekna\n"


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

    @staticmethod
    async def test_a_stop_is_heard_and_is_not_a_cast(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        assert not daemon.messages
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_stop_is_logged_with_who_asked_and_who_started_them(
        socket_path: Path, caplog: pytest.LogCaptureFixture
    ):
        caplog.set_level(logging.INFO)
        server = await _Daemon().start(socket_path)
        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        [said] = caplog.messages
        assert said.startswith(
            f"stop asked by pid {os.getpid()} ({_command(os.getpid())}),"
            f" started by pid {os.getppid()} ("
        )
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_stop_from_a_process_that_cannot_be_named_is_still_logged(
        socket_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.delattr(socket, "SO_PEERCRED")
        server = await _Daemon().start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        assert caplog.messages == ["stop asked by a process this system does not name"]
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_stop_from_a_process_already_gone_is_logged_by_its_pid(
        socket_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Path, "read_bytes", _unreadable)
        monkeypatch.setattr(Path, "read_text", _unreadable)
        server = await _Daemon().start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        assert caplog.messages == [f"stop asked by pid {os.getpid()} (gone)"]
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_stop_from_a_peer_the_system_will_not_describe_is_still_logged(
        socket_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(socket, "SO_PEERCRED", 0)
        server = await _Daemon().start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        assert caplog.messages == ["stop asked by a process this system does not name"]
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_stop_from_a_process_with_no_parent_field_is_logged_by_its_pid(
        socket_path: Path,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ):
        caplog.set_level(logging.INFO)
        monkeypatch.setattr(Path, "read_text", _without_parent)
        server = await _Daemon().start(socket_path)

        _, writer = await attach(socket_path)
        writer.write(encode_frame(StopRequested()))
        await writer.drain()
        await asyncio.wait_for(server.stopped(), timeout=2)

        assert caplog.messages == [f"stop asked by pid {os.getpid()}"]
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_cast_asking_for_room_is_answered_down_its_connection(
        socket_path: Path,
    ):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        refusal = await admission_refusal(socket_path, "/proj")

        assert refusal == "full"
        assert daemon.requests == [AdmissionRequested(project_root="/proj")]
        assert not daemon.attached
        await server.close()

    @staticmethod
    async def test_an_altar_is_answered_down_its_connection(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        reader, writer = await attach(socket_path)
        asked = AltarRequested(project_root="/proj", fix=True, save=True, tree=1)
        writer.write(encode_frame(asked))
        await writer.drain()
        reply = [message async for message in read_frames(reader)]

        assert reply == [AltarTended(trees=[HeldTree(path="/proj/1")])]
        assert daemon.requests == [asked]
        assert not daemon.attached
        writer.close()
        await server.close()

    @staticmethod
    async def test_a_cast_asked_for_first_is_answered_down_its_connection(
        socket_path: Path,
    ):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        reader, writer = await attach(socket_path)
        asked = CastRequested(project_root="/proj", ritual="nap", components={})
        writer.write(encode_frame(asked))
        await writer.drain()
        reply = [message async for message in read_frames(reader)]

        assert reply == [CastQueued(cast_id="c1")]
        assert daemon.requests == [asked]
        assert not daemon.attached
        writer.close()
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

    @staticmethod
    async def test_a_version_is_answered_down_its_connection(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        reader, writer = await attach(socket_path)
        writer.write(encode_frame(VersionRequested()))
        await writer.drain()
        reply = [message async for message in read_frames(reader)]

        assert reply == [DaemonVersion(version=VERSION)]
        assert not daemon.attached
        assert not daemon.messages
        writer.close()
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

    # The cast runs on and rejoins the next daemon: ended here, its tree would
    # be freed under it and the cast awaiting it told that it died.
    @staticmethod
    async def test_a_cast_the_daemon_hangs_up_on_is_not_said_goodbye_for(
        socket_path: Path,
    ):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        reader, writer = await attach(socket_path)
        writer.write(encode_frame(_hello()))
        await writer.drain()
        await _eventually(lambda: bool(daemon.messages))

        await server.close()
        assert not await reader.read()
        await _settle()

        assert daemon.messages == [_hello()]
        assert daemon.closed == ["c1"]
        writer.close()

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
    async def test_a_surface_claims_releases_and_answers_as_itself(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        claimed = DecideClaimed(cast_id="c1", request_id="q1", claim_id="k1")
        released = DecideReleased(cast_id="c1", request_id="q1")
        resolved = DecideResolved(cast_id="c1", request_id="q1", answer="yes")
        writer.write(encode_frame(SurfaceHello()))
        writer.write(encode_frame(claimed))
        writer.write(encode_frame(released))
        writer.write(encode_frame(resolved))
        await writer.drain()
        await _settle()

        writer.close()
        await _settle()

        surface = daemon.attached[0]
        assert daemon.prompted == [
            (surface, claimed),
            (surface, released),
            (surface, resolved),
        ]
        await server.close()

    @staticmethod
    async def test_a_surface_cancels_a_cast_as_itself(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)
        _, writer = await attach(socket_path)
        cancel = CastCancelRequested(cast_id="c1")
        writer.write(encode_frame(SurfaceHello()))
        writer.write(encode_frame(cancel))
        await writer.drain()
        await _settle()

        writer.close()
        await _settle()

        assert daemon.prompted == [(daemon.attached[0], cancel)]
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
        daemon = _Unwritable()
        server = await daemon.start(socket_path)
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


@pytest.mark.asyncio
class TestMarkSeen:
    @staticmethod
    async def test_a_mark_is_answered_down_its_connection(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        refusal = await mark_seen(socket_path, CastSeen(cast_id="c1"))

        assert refusal is None
        assert daemon.requests == [CastSeen(cast_id="c1")]
        assert not daemon.attached
        await server.close()

    @staticmethod
    async def test_a_daemon_that_hangs_up_on_the_mark_predates_it(socket_path: Path):
        async def hang_up(
            _: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(hang_up, path=str(socket_path))

        refusal = await mark_seen(socket_path, CastSeen(cast_id="c1"))

        assert refusal == (
            "this daemon predates marking a cast seen: `vekna stop` ends it, and"
            " the next `vekna` starts one that marks"
        )
        server.close()
        await server.wait_closed()

    @staticmethod
    async def test_no_daemon_listening_says_so(socket_path: Path):
        refusal = await mark_seen(socket_path, CastSeen(cast_id="c1"))

        assert refusal is not None
        assert refusal.startswith("the daemon did not take the mark: ")


@pytest.mark.asyncio
class TestVigilsPaused:
    @staticmethod
    async def test_a_pause_is_answered_down_its_connection(socket_path: Path):
        daemon = _Daemon()
        server = await daemon.start(socket_path)

        paused = await set_vigils_paused(socket_path, paused=True)
        asked = await vigils_paused(socket_path)

        assert (paused, asked) == (True, False)
        assert daemon.requests == [VigilsRequested(pause=True), VigilsRequested()]
        assert not daemon.attached
        await server.close()

    @staticmethod
    async def test_a_daemon_that_hangs_up_on_the_question_does_not_say(
        socket_path: Path,
    ):
        async def hang_up(
            _: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(hang_up, path=str(socket_path))

        paused = await set_vigils_paused(socket_path, paused=True)

        assert paused is None
        server.close()
        await server.wait_closed()

    @staticmethod
    async def test_no_daemon_listening_does_not_say(socket_path: Path):
        assert await vigils_paused(socket_path) is None
