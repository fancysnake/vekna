from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from vekna.links.socket_client import SocketClientLink
from vekna.links.socket_server import SocketServerLink
from vekna.pacts.notify import OK_RESPONSE


class TestNotifyFlow:
    @staticmethod
    @pytest.fixture
    def socket_path(tmp_path: Path) -> str:
        return str(tmp_path / "test.sock")

    @staticmethod
    @pytest.mark.asyncio
    async def test_client_sends_to_server_handler(socket_path) -> None:
        handler = AsyncMock(return_value=OK_RESPONSE.model_dump_json())
        server = SocketServerLink(socket_path=socket_path)
        client = SocketClientLink(socket_path=socket_path)

        await server.start(handler)
        response = await client.send('{"pane_id": "%2"}')
        await server.stop()

        handler.assert_called_once_with('{"pane_id": "%2"}')
        assert response == OK_RESPONSE.model_dump_json()
