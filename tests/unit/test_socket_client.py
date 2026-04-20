import asyncio
from pathlib import Path

import pytest

from vekna.links.socket_client import SocketClientLink
from vekna.pacts.notify import OK_RESPONSE


def _socket_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.sock")


class TestSocketClient:
    @staticmethod
    @pytest.fixture
    def socket_path(tmp_path: Path) -> str:
        return _socket_path(tmp_path)

    @staticmethod
    @pytest.mark.asyncio
    async def test_sends_message_and_returns_response(socket_path) -> None:
        received: list[str] = []

        async def handler(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            line = await reader.readline()
            received.append(line.decode().strip())
            writer.write(f"{OK_RESPONSE.model_dump_json()}\n".encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(handler, path=socket_path)
        client = SocketClientLink(socket_path=socket_path)

        result = await client.send('{"pane_id": "%1"}')

        server.close()
        await server.wait_closed()

        assert received == ['{"pane_id": "%1"}']
        assert result == OK_RESPONSE.model_dump_json()
