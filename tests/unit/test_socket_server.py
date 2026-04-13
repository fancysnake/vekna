import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from vekna.links.socket_server import SocketServerLink
from vekna.pacts.notify import OK_RESPONSE


def _socket_exists(socket_path: str) -> bool:
    return Path(socket_path).exists()


class TestSocketServer:
    @staticmethod
    @pytest.fixture
    def socket_path(tmp_path: Path) -> str:
        return str(tmp_path / "test.sock")

    @staticmethod
    @pytest.mark.asyncio
    async def test_accepts_connection_and_calls_handler(socket_path) -> None:
        handler = AsyncMock(return_value=OK_RESPONSE)
        server = SocketServerLink(socket_path=socket_path)

        await server.start(handler)
        reader, writer = await asyncio.open_unix_connection(socket_path)
        writer.write(b'{"pane_id": "%1"}\n')
        await writer.drain()
        response = await reader.readline()
        writer.close()
        await writer.wait_closed()
        await server.stop()

        handler.assert_called_once_with('{"pane_id": "%1"}')
        assert response == f"{OK_RESPONSE}\n".encode()

    @staticmethod
    @pytest.mark.asyncio
    async def test_stop_removes_socket_file(socket_path) -> None:
        handler = AsyncMock(return_value=OK_RESPONSE)
        server = SocketServerLink(socket_path=socket_path)

        await server.start(handler)
        assert _socket_exists(socket_path)
        await server.stop()

        assert not _socket_exists(socket_path)
