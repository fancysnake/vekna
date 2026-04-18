import json
from unittest.mock import AsyncMock

import pytest

from vekna.mills.notify import NotifyClientMill
from vekna.pacts.notify import OK_RESPONSE


class TestNotify:
    @staticmethod
    @pytest.mark.asyncio
    async def test_sends_event_with_all_fields() -> None:
        socket_client = AsyncMock(return_value=OK_RESPONSE)
        mill = NotifyClientMill(socket_client=socket_client)

        await mill.notify(
            app="claude",
            hook="Notification",
            payload='{"title": "done"}',
            meta={"TMUX_PANE": "%5"},
        )

        socket_client.send.assert_called_once()
        sent = json.loads(socket_client.send.call_args[0][0])
        assert sent == {
            "app": "claude",
            "hook": "Notification",
            "payload": '{"title": "done"}',
            "meta": {"TMUX_PANE": "%5"},
        }
