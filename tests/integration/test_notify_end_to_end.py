"""End-to-end notify flow test.

NotifyClientMill -> socket -> ServerMill -> EventBus ->
ClaudeNotificationHandler -> SelectPaneHandler -> TmuxLink.select_pane.
TmuxLink is the only mock; everything else is the real implementation.
"""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vekna.links.socket_client import SocketClientLink
from vekna.links.socket_server import SocketServerLink
from vekna.mills.bus import EventBus
from vekna.mills.handlers import ClaudeNotificationHandler, SelectPaneHandler
from vekna.mills.notify import NotifyClientMill
from vekna.mills.server import ServerMill
from vekna.pacts.bus import App, Hook
from vekna.specs import ATTENTION_POLL_INTERVAL_SECONDS, IDLE_THRESHOLD_SECONDS

_PANE_ID = "%3"


def _make_tmux(*, seconds_idle: float) -> MagicMock:
    tmux = MagicMock()
    tmux.last_activity_seconds_ago.return_value = seconds_idle
    return tmux


async def _run(socket_path: str, tmux: MagicMock, payload: str = "{}") -> None:
    socket_server = SocketServerLink(socket_path=socket_path)
    bus = EventBus()
    bus.register(
        App.VEKNA,
        Hook.SELECT_PANE,
        SelectPaneHandler(
            tmux, IDLE_THRESHOLD_SECONDS, ATTENTION_POLL_INTERVAL_SECONDS
        ),
    )
    bus.register(App.CLAUDE, Hook.NOTIFICATION, ClaudeNotificationHandler(bus))

    server = ServerMill(tmux=tmux, socket_server=socket_server, bus=bus)
    await socket_server.start(server.handle)

    client = NotifyClientMill(socket_client=SocketClientLink(socket_path=socket_path))
    await client.notify(
        app="claude", hook="Notification", payload=payload, meta={"TMUX_PANE": _PANE_ID}
    )

    # Let all bus tasks complete.
    await asyncio.gather(
        *asyncio.all_tasks() - {asyncio.current_task()}, return_exceptions=True
    )
    await socket_server.stop()


class TestNotifyEndToEnd:
    @staticmethod
    @pytest.fixture
    def socket_path(tmp_path: Path) -> str:
        return str(tmp_path / "vekna.sock")

    @staticmethod
    @pytest.mark.asyncio
    async def test_select_pane_called_when_user_is_idle(socket_path: str) -> None:
        tmux = _make_tmux(seconds_idle=IDLE_THRESHOLD_SECONDS + 10.0)

        await _run(socket_path, tmux)

        tmux.select_pane.assert_called_once_with(_PANE_ID)

    @staticmethod
    @pytest.mark.asyncio
    async def test_select_pane_skipped_when_user_is_active(socket_path: str) -> None:
        tmux = _make_tmux(seconds_idle=IDLE_THRESHOLD_SECONDS - 0.1)

        await _run(socket_path, tmux)

        tmux.select_pane.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_payload_is_forwarded_through_chain(socket_path: str) -> None:
        tmux = _make_tmux(seconds_idle=IDLE_THRESHOLD_SECONDS + 10.0)
        payload = '{"title": "Tests passed", "session_id": "abc"}'

        await _run(socket_path, tmux, payload=payload)

        tmux.select_pane.assert_called_once_with(_PANE_ID)
