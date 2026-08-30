import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from vekna.pacts.routing import SocketPathError, Surface
from vekna.wire import (
    CastGoodbye,
    CastMessage,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

_SOCKET_MODE = 0o600
_CONNECT_SECONDS = 2.0
# One frame is one line, and a rite's result is a field of it: a shell medium
# hands back everything the command printed, so `git diff` against a branch is a
# single frame of megabytes. asyncio's stream default is 64KiB, and a frame over
# it is a `ValueError` — read as an unreadable frame, which ends the connection
# and marks a cast that is still running as aborted.
# ponytail: a ceiling, not a fix. A result bigger than this still ends the
# connection; framing the length ahead of the payload is the upgrade.
_FRAME_LIMIT = 32 * 1024 * 1024
_GONE = "socket closed without a goodbye"
_NOT_ITS_OWN = "sent a frame for cast"


# Writes are buffered, never awaited: a surface that has stopped reading must
# not be able to stall the cast whose event it is being sent.
# ponytail: unbounded buffer. A surface that never drains grows the daemon's
# memory; dropping it after a high-water mark is the upgrade.
class SocketSurface(Surface):
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer

    def send(self, message: WireMessage) -> None:
        self._writer.write(encode_frame(message))


# Closing the server only stops it accepting; the connections it already handed
# out stay open. A daemon that ends has to take them with it, or a peer surface
# is left painting a view nobody will ever change again.
class Serving:
    def __init__(
        self, server: asyncio.Server, writers: set[asyncio.StreamWriter]
    ) -> None:
        self._server = server
        self._writers = writers

    # Awaited one by one rather than left to `wait_closed`, which on 3.11 comes
    # back the moment the server stops accepting: what is buffered for a peer
    # surface is written as the daemon ends, not dropped with it.
    async def close(self) -> None:
        self._server.close()
        closing = list(self._writers)
        for writer in closing:
            writer.close()
        await self._server.wait_closed()
        for writer in closing:
            with contextlib.suppress(OSError):
                await writer.wait_closed()


async def alive(path: Path) -> bool:
    # `TimeoutError` is an `OSError` from 3.11 on, so the bound `attach` puts on
    # the connect needs nothing said about it here.
    try:
        _, writer = await attach(path)
    except OSError:
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


# Bounded, because a connect to a listening socket whose backlog is full waits
# rather than failing: a daemon wedged that way would otherwise hang the next
# `vekna` — on its liveness probe, with nothing on screen to say why.
async def attach(path: Path) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.wait_for(
        asyncio.open_unix_connection(str(path), limit=_FRAME_LIMIT),
        timeout=_CONNECT_SECONDS,
    )


# Binds, having been asked. Whether there is already a daemon here is `alive`'s
# question and the caller's decision — the answer is what makes it a peer
# instead, so it belongs where that branch is taken.
# The check has to come first either way, because `create_unix_server` unlinks
# an existing socket file for us: bind never reports the address as taken, so a
# second daemon would silently steal the first one's socket and leave it
# listening where nothing can reach it.
# ponytail: a live check then a bind, so two daemons starting in the same
# millisecond can still race. A lock file opened O_EXCL is the upgrade, and it
# costs a stale-lock story that this does not.
async def serve(
    *,
    path: Path,
    on_message: Callable[[CastMessage], None],
    on_attach: Callable[[Surface], None],
    on_detach: Callable[[Surface], None],
) -> Serving:
    writers: set[asyncio.StreamWriter] = set()

    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writers.add(writer)
        try:
            await _handle(
                reader,
                writer,
                on_message=on_message,
                on_attach=on_attach,
                on_detach=on_detach,
            )
        finally:
            writers.discard(writer)

    if await asyncio.to_thread(_occupied, path):
        msg = f"{path} is not a socket — vekna has nowhere to bind"
        raise SocketPathError(msg)
    server = await asyncio.start_unix_server(handle, path=str(path), limit=_FRAME_LIMIT)
    await asyncio.to_thread(path.chmod, _SOCKET_MODE)
    return Serving(server, writers)


# A dead socket file is cleared away by `create_unix_server` itself. Anything
# else at that path is somebody's file, and is not vekna's to delete.
def _occupied(path: Path) -> bool:
    return path.exists() and not path.is_socket()


# What a connection opens with is what it is, and that is settled once: a
# surface is fanned out to, anything else is a cast and is routed. The first
# frame is the only place the two can be told apart, so it is the only place
# that asks.
async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    on_message: Callable[[CastMessage], None],
    on_attach: Callable[[Surface], None],
    on_detach: Callable[[Surface], None],
) -> None:
    frames = aiter(read_frames(reader))
    try:
        opened = await _opening(frames)
        if isinstance(opened, SurfaceHello):
            await _as_surface(frames, writer, on_attach=on_attach, on_detach=on_detach)
        elif opened is not None:
            await _as_cast(opened, frames, on_message=on_message)
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


# A connection that says nothing readable is nobody, and there is no cast to
# tell about it — which is the one case the goodbye below cannot cover.
async def _opening(frames: AsyncIterator[WireMessage]) -> WireMessage | None:
    with contextlib.suppress(StopAsyncIteration, ValueError, OSError):
        return await anext(frames)
    return None


# A surface is sent to and not heard from: answering a prompt from `vekna`
# itself is deferred, so what arrives after the handshake is read to notice the
# disconnect and nothing else.
async def _as_surface(
    frames: AsyncIterator[WireMessage],
    writer: asyncio.StreamWriter,
    *,
    on_attach: Callable[[Surface], None],
    on_detach: Callable[[Surface], None],
) -> None:
    surface = SocketSurface(writer)
    on_attach(surface)
    try:
        with contextlib.suppress(ValueError, OSError):
            async for _ in frames:
                pass
    finally:
        on_detach(surface)


# A cast that goes without a goodbye gets one anyway, or the daemon would hold
# it as running for as long as it runs.
# A frame this daemon cannot read, and a connection lost mid-frame, both end
# this one connection and say so in that goodbye: killing the daemon over
# either would take every other cast down with it.
# Whose cast this is was settled by the opening frame, so a frame naming another
# one is not routed: it would otherwise let any process on this account write
# into a cast it is not — and a `CastGoodbye` for somebody else would count as
# this connection's own, leaving the cast that did open it running forever.
async def _as_cast(
    opened: CastMessage,
    frames: AsyncIterator[WireMessage],
    *,
    on_message: Callable[[CastMessage], None],
) -> None:
    said_goodbye = isinstance(opened, CastGoodbye)

    # Noted on the way past rather than read back off the loop, because reading
    # is what raises: a cast that said goodbye and then lost its socket must not
    # be told it disconnected on top of the ending it gave itself.
    def heard(message: CastMessage) -> None:
        nonlocal said_goodbye
        on_message(message)
        said_goodbye = isinstance(message, CastGoodbye)

    detail = _GONE
    try:
        heard(opened)
        detail = await _reading(opened, frames, on_message=heard)
    except ValueError as error:
        detail = f"unreadable frame: {error}"
    except OSError as error:
        detail = f"connection lost: {error}"
    finally:
        if not said_goodbye:
            on_message(
                CastGoodbye(
                    cast_id=opened.cast_id, status="disconnected", detail=detail
                )
            )


# Why the reading ended, for the goodbye above to carry.
async def _reading(
    opened: CastMessage,
    frames: AsyncIterator[WireMessage],
    *,
    on_message: Callable[[CastMessage], None],
) -> str:
    async for message in frames:
        if isinstance(message, SurfaceHello):
            continue
        if message.cast_id != opened.cast_id:
            return f"{_NOT_ITS_OWN} {message.cast_id!r}"
        on_message(message)
    return _GONE
