"""End-to-end daemon integration test.

Starts ServerMill in a background thread, connects via real Unix socket,
exercises EnsureSession → notify → StatusBar → EnsureSession (ack) flow.
TmuxLink is the only mock; all other components are real.
"""

import asyncio
import contextlib
import json
import socket as _socket
import threading
import time
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
from vekna.pacts.notify import Event
from vekna.specs import ATTENTION_POLL_INTERVAL_SECONDS, IDLE_THRESHOLD_SECONDS

_PANE_ID = "%5"
_SESSION_NAME = "vekna-myproject-abc123"


def _make_tmux() -> MagicMock:
    tmux = MagicMock()
    tmux.session_name_for_pane.return_value = _SESSION_NAME
    tmux.last_activity_seconds_ago.return_value = IDLE_THRESHOLD_SECONDS - 1.0
    return tmux


def _build_server(socket_path: str, tmux: MagicMock) -> ServerMill:
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
    return ServerMill(
        tmux=tmux,
        socket_server=socket_server,
        bus=bus,
        session_name_for_cwd=lambda cwd: f"vekna-{Path(cwd).name}-abc123",
    )


def _wait_for_socket(socket_path: str) -> None:
    for _ in range(30):
        with contextlib.suppress(OSError):
            with _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM) as s:
                s.connect(socket_path)
            return
        time.sleep(0.05)


class TestDaemonEndToEnd:
    @staticmethod
    @pytest.fixture
    def socket_path(tmp_path: Path) -> str:
        return str(tmp_path / "vekna.sock")

    @staticmethod
    @pytest.fixture
    def tmux() -> MagicMock:
        return _make_tmux()

    @staticmethod
    @pytest.fixture
    def running_server(socket_path, tmux):
        server = _build_server(socket_path, tmux)
        loop = asyncio.new_event_loop()

        async def _run_and_stop() -> None:
            try:
                await server.run()
            except asyncio.CancelledError:
                pass
            finally:
                loop.stop()

        def run() -> None:
            asyncio.set_event_loop(loop)
            task = loop.create_task(_run_and_stop())
            task_holder.append(task)
            loop.run_forever()

        task_holder: list[asyncio.Task] = []
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        _wait_for_socket(socket_path)

        yield

        loop.call_soon_threadsafe(task_holder[0].cancel)
        thread.join(timeout=2.0)
        loop.close()

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("running_server")
    async def test_ensure_session_creates_session(socket_path, tmux) -> None:
        client = NotifyClientMill(
            socket_client=SocketClientLink(socket_path=socket_path)
        )

        response = await client.request(
            Event(
                app=App.VEKNA,
                hook=Hook.ENSURE_SESSION,
                payload="",
                meta={"cwd": "/tmp/myproject"},
            )
        )

        assert response.status == "ok"
        assert response.data["session_name"] == _SESSION_NAME
        tmux.ensure_session.assert_called_once_with(_SESSION_NAME, "/tmp/myproject")

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("running_server")
    async def test_notify_increments_pending_count(socket_path) -> None:
        client = NotifyClientMill(
            socket_client=SocketClientLink(socket_path=socket_path)
        )
        await client.request(
            Event(
                app=App.VEKNA,
                hook=Hook.ENSURE_SESSION,
                payload="",
                meta={"cwd": "/tmp/myproject"},
            )
        )
        await client.notify(
            app=App.CLAUDE,
            hook=Hook.NOTIFICATION,
            payload="{}",
            meta={"TMUX_PANE": _PANE_ID},
        )
        await asyncio.sleep(0.05)

        response = await client.request(
            Event(app=App.VEKNA, hook=Hook.STATUS_BAR, payload="", meta={})
        )

        data = json.loads(response.model_dump_json())
        assert "myproject(1)" in data["data"]["text"]

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("running_server")
    async def test_ensure_session_resets_pending_count(socket_path) -> None:
        client = NotifyClientMill(
            socket_client=SocketClientLink(socket_path=socket_path)
        )
        await client.request(
            Event(
                app=App.VEKNA,
                hook=Hook.ENSURE_SESSION,
                payload="",
                meta={"cwd": "/tmp/myproject"},
            )
        )
        await client.notify(
            app=App.CLAUDE,
            hook=Hook.NOTIFICATION,
            payload="{}",
            meta={"TMUX_PANE": _PANE_ID},
        )
        await asyncio.sleep(0.05)

        await client.request(
            Event(
                app=App.VEKNA,
                hook=Hook.ENSURE_SESSION,
                payload="",
                meta={"cwd": "/tmp/myproject"},
            )
        )
        response = await client.request(
            Event(app=App.VEKNA, hook=Hook.STATUS_BAR, payload="", meta={})
        )

        data = json.loads(response.model_dump_json())
        assert _SESSION_NAME not in data["data"]["text"]

    @staticmethod
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("running_server")
    async def test_status_bar_shows_badge_when_no_pending(socket_path) -> None:
        client = NotifyClientMill(
            socket_client=SocketClientLink(socket_path=socket_path)
        )

        response = await client.request(
            Event(app=App.VEKNA, hook=Hook.STATUS_BAR, payload="", meta={})
        )

        data = json.loads(response.model_dump_json())
        assert "vekna" in data["data"]["text"]
