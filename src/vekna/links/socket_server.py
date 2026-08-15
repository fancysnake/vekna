import asyncio
import contextlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from vekna.pacts.routing import SocketPathError, Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

_SOCKET_MODE = 0o600
_CONNECT_SECONDS = 2.0
_GONE = "socket closed without a goodbye"
_SOCKET_ENV = "VEKNA_SOCKET"


# The same path the lexicon's probe computes, written twice because the daemon
# may not import the lexicon. Both read `VEKNA_SOCKET` first, which is what lets
# a test — or two users on one machine — stand up a socket of their own.
def default_socket_path() -> Path:
    if (named := os.environ.get(_SOCKET_ENV)) is not None:
        return Path(named)
    return Path(tempfile.gettempdir()) / f"vekna-{os.getuid()}.sock"


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
        asyncio.open_unix_connection(str(path)), timeout=_CONNECT_SECONDS
    )


# None when another daemon already holds the socket — the caller attaches to it
# as a peer instead. A socket file nobody answers is the leftover of a daemon
# that was killed, and is unlinked rather than left to refuse every start from
# here on.
# Asked before binding rather than after a failure, because `create_unix_server`
# unlinks an existing socket file for us: bind never reports the address as
# taken, so a second daemon would silently steal the first one's socket and
# leave it listening where nothing can reach it.
# ponytail: a live check then a bind, so two daemons starting in the same
# millisecond can still race. A lock file opened O_EXCL is the upgrade, and it
# costs a stale-lock story that this does not.
async def serve(
    *,
    path: Path,
    on_message: Callable[[CastMessage], None],
    on_attach: Callable[[Surface], None],
    on_detach: Callable[[Surface], None],
) -> Serving | None:
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

    if await alive(path):
        return None
    if await asyncio.to_thread(_occupied, path):
        msg = f"{path} is not a socket — vekna has nowhere to bind"
        raise SocketPathError(msg)
    server = await asyncio.start_unix_server(handle, path=str(path))
    await asyncio.to_thread(path.chmod, _SOCKET_MODE)
    return Serving(server, writers)


# A dead socket file is cleared away by `create_unix_server` itself. Anything
# else at that path is somebody's file, and is not vekna's to delete.
def _occupied(path: Path) -> bool:
    return path.exists() and not path.is_socket()


class _Connection:
    def __init__(self) -> None:
        self.surface: SocketSurface | None = None
        self.cast_id: str | None = None
        self.said_goodbye = False

    def note(self, message: CastMessage) -> None:
        if isinstance(message, CastHello):
            self.cast_id = message.cast_id
        elif isinstance(message, CastGoodbye):
            self.said_goodbye = True


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    on_message: Callable[[CastMessage], None],
    on_attach: Callable[[Surface], None],
    on_detach: Callable[[Surface], None],
) -> None:
    connection = _Connection()
    detail = _GONE
    try:
        await _pump(
            reader, writer, connection, on_message=on_message, on_attach=on_attach
        )
    # A frame this daemon cannot read ends that one connection and says why in
    # the cast's own goodbye. Killing the daemon over it would take every other
    # cast down with it.
    except ValueError as error:
        detail = f"unreadable frame: {error}"
    # A peer that dies mid-frame resets the connection rather than closing it.
    # The goodbye is the same either way, and carrying the cause in it beats
    # letting asyncio log a traceback for a routine disconnect.
    except OSError as error:
        detail = f"connection lost: {error}"
    finally:
        _close(connection, on_message=on_message, on_detach=on_detach, detail=detail)
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


async def _pump(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    connection: _Connection,
    *,
    on_message: Callable[[CastMessage], None],
    on_attach: Callable[[Surface], None],
) -> None:
    # The one place a `SurfaceHello` is a message rather than a handshake, and
    # where it stops: everything downstream takes a `CastMessage`, so a surface
    # saying hello twice is the same attachment, not something to route.
    async for message in read_frames(reader):
        if isinstance(message, SurfaceHello):
            if connection.surface is None:
                connection.surface = SocketSurface(writer)
                on_attach(connection.surface)
            continue
        connection.note(message)
        on_message(message)


def _close(
    connection: _Connection,
    *,
    on_message: Callable[[CastMessage], None],
    on_detach: Callable[[Surface], None],
    detail: str,
) -> None:
    if connection.surface is not None:
        on_detach(connection.surface)
    if connection.cast_id is not None and not connection.said_goodbye:
        on_message(
            CastGoodbye(
                cast_id=connection.cast_id, status="disconnected", detail=detail
            )
        )
