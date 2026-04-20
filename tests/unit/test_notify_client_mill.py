import json
from unittest.mock import AsyncMock

import pytest

from vekna.mills.notify import NotifyClientMill
from vekna.pacts.notify import OK_RESPONSE, Event
from vekna.pacts.socket import Response


class TestNotify:
    @staticmethod
    @pytest.mark.asyncio
    async def test_sends_event_with_all_fields() -> None:
        socket_client = AsyncMock()
        socket_client.send = AsyncMock(return_value=OK_RESPONSE.model_dump_json())
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


class TestRequest:
    @staticmethod
    @pytest.mark.asyncio
    async def test_sends_event_and_returns_parsed_response() -> None:
        response = Response(status="ok", data={"session_name": "vekna-foo-a1b2c3"})
        socket_client = AsyncMock()
        socket_client.send = AsyncMock(return_value=response.model_dump_json())
        mill = NotifyClientMill(socket_client=socket_client)
        event = Event(
            app="vekna", hook="EnsureSession", payload="", meta={"cwd": "/tmp/foo"}
        )

        result = await mill.request(event)

        socket_client.send.assert_called_once()
        sent = json.loads(socket_client.send.call_args[0][0])
        assert sent == {
            "app": "vekna",
            "hook": "EnsureSession",
            "payload": "",
            "meta": {"cwd": "/tmp/foo"},
        }
        assert result == response
