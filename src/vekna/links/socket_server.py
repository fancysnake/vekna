import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class SocketServerLink:
    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path
        self._server: asyncio.Server | None = None
        self._handler: Callable[[str], Awaitable[str]] | None = None

    async def start(self, handler: Callable[[str], Awaitable[str]]) -> None:
        self._handler = handler
        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=self._socket_path
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        self._cleanup_socket()

    def _cleanup_socket(self) -> None:
        path = Path(self._socket_path)
        if path.exists():
            path.unlink()

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        line = await reader.readline()
        message = line.decode().strip()
        if self._handler is not None:
            response = await self._handler(message)
            writer.write(f"{response}\n".encode())
            await writer.drain()
        writer.close()
        await writer.wait_closed()
