import json
from unittest.mock import AsyncMock

import pytest

from vekna.mills.notify import NotifyClientMill
from vekna.pacts.notify import OK_RESPONSE


class TestNotify:
    @staticmethod
    @pytest.mark.asyncio
    async def test_sends_notify_request_with_pane_id() -> None:
        socket_client = AsyncMock(return_value=OK_RESPONSE)
        mill = NotifyClientMill(socket_client=socket_client)

        await mill.notify("%5")

        socket_client.send.assert_called_once()
        sent = json.loads(socket_client.send.call_args[0][0])
        assert sent == {"pane_id": "%5"}
