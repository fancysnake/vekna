import asyncio
import contextlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from vekna.mills.server import ServerMill
from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE, Event
from vekna.specs.session import stem_for_cwd

_SESSION_NAME_FOR_CWD = staticmethod(lambda cwd: f"vekna-{cwd.split('/')[-1]}-abc123")

# Badge emitted when no session_name is passed
# (falls back to skull: dark red bg, white fg).
_FALLBACK_BADGE = "#[bg=colour88,fg=colour231] ☠️ vekna #[bg=default,fg=colour245]"


def _make_tmux() -> MagicMock:
    tmux = MagicMock()
    tmux.session_name_for_pane.return_value = "work"
    return tmux


def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.drain = AsyncMock()
    return bus


def _make_mill(tmux: MagicMock, socket_server: AsyncMock) -> ServerMill:
    return ServerMill(
        tmux=tmux,
        socket_server=socket_server,
        bus=_make_bus(),
        session_name_for_cwd=_SESSION_NAME_FOR_CWD,
    )


def _event_json(pane_id: str = "%3") -> str:
    return (
        f'{{"app": "claude", "hook": "Notification",'
        f' "payload": "{{}}", "meta": {{"TMUX_PANE": "{pane_id}"}}}}'
    )


async def _run_and_cancel(mill: ServerMill) -> None:
    task = asyncio.create_task(mill.run())
    await asyncio.sleep(0)  # let run() start and reach its own sleep(0)
    await asyncio.sleep(0)  # let run()'s sleep(0) complete, now at Event().wait()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class TestRun:
    @staticmethod
    @pytest.mark.asyncio
    async def test_starts_socket_server() -> None:
        socket_server = AsyncMock()
        mill = _make_mill(_make_tmux(), socket_server)

        await _run_and_cancel(mill)

        socket_server.start.assert_called_once()

    @staticmethod
    @pytest.mark.asyncio
    async def test_stops_socket_server_on_cancellation() -> None:
        socket_server = AsyncMock()
        mill = _make_mill(_make_tmux(), socket_server)

        await _run_and_cancel(mill)

        socket_server.stop.assert_called_once_with()

    @staticmethod
    @pytest.mark.asyncio
    async def test_cancels_background_tasks_on_cancellation() -> None:
        socket_server = AsyncMock()
        cancelled: list[bool] = []

        async def bg() -> None:
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=socket_server,
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
            background=[bg],
        )

        await _run_and_cancel(mill)

        assert cancelled == [True]

    @staticmethod
    @pytest.mark.asyncio
    async def test_drains_bus_on_cancellation() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        await _run_and_cancel(mill)

        bus.drain.assert_awaited_once()


class TestHandle:
    @staticmethod
    @pytest.mark.asyncio
    async def test_publishes_event_to_bus() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        result = await mill.handle(_event_json("%3"))

        bus.publish.assert_called_once_with(
            Event(
                app="claude",
                hook="Notification",
                payload="{}",
                meta={"TMUX_PANE": "%3"},
            )
        )
        assert result == OK_RESPONSE.model_dump_json()

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_ok_for_valid_event() -> None:
        mill = _make_mill(_make_tmux(), AsyncMock())

        result = await mill.handle(_event_json())

        assert result == OK_RESPONSE.model_dump_json()

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_json() -> None:
        mill = _make_mill(_make_tmux(), AsyncMock())

        result = await mill.handle("not json")

        assert result == ERROR_RESPONSE_INVALID.model_dump_json()

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_publish_on_invalid_message() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        await mill.handle("not json")

        bus.publish.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_increments_pending_on_claude_notification() -> None:
        tmux = _make_tmux()
        tmux.session_name_for_pane.return_value = "work"
        mill = ServerMill(
            tmux=tmux,
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        await mill.handle(_event_json("%3"))
        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        data = json.loads(result)
        assert data["data"]["text"] == _FALLBACK_BADGE + "work(1)"

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_increment_pending_without_tmux_pane() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )
        event_json = (
            '{"app": "claude", "hook": "Notification", "payload": "{}", "meta": {}}'
        )

        await mill.handle(event_json)
        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        data = json.loads(result)
        assert data["data"]["text"] == _FALLBACK_BADGE


class TestHandleEnsureSession:
    @staticmethod
    @pytest.mark.asyncio
    async def test_creates_session_and_returns_session_name() -> None:
        tmux = _make_tmux()
        mill = ServerMill(
            tmux=tmux,
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        ensure_msg = (
            '{"app": "vekna", "hook": "EnsureSession",'
            ' "payload": "", "meta": {"cwd": "/tmp/foo"}}'
        )
        result = await mill.handle(ensure_msg)

        data = json.loads(result)
        assert data["status"] == "ok"
        session_name = data["data"]["session_name"]
        assert session_name.startswith("vekna-foo-")
        tmux.ensure_session.assert_called_once_with(session_name, "/tmp/foo")

    @staticmethod
    @pytest.mark.asyncio
    async def test_resets_pending_count_on_ensure_session() -> None:
        tmux = _make_tmux()
        tmux.session_name_for_pane.return_value = "vekna-foo-abc123"
        mill = ServerMill(
            tmux=tmux,
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )
        # Simulate a pending notification
        await mill.handle(_event_json("%3"))

        # EnsureSession should clear the pending count
        ensure_msg = (
            '{"app": "vekna", "hook": "EnsureSession",'
            ' "payload": "", "meta": {"cwd": "/tmp/foo"}}'
        )
        await mill.handle(ensure_msg)
        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        data = json.loads(result)
        assert data["data"]["text"] == _FALLBACK_BADGE

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_publish_ensure_session_to_bus() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )
        ensure_msg = (
            '{"app": "vekna", "hook": "EnsureSession",'
            ' "payload": "", "meta": {"cwd": "/tmp/foo"}}'
        )

        await mill.handle(ensure_msg)

        bus.publish.assert_not_called()


class TestClearPending:
    @staticmethod
    @pytest.mark.asyncio
    async def test_clears_pending_count_for_session() -> None:
        tmux = _make_tmux()
        tmux.session_name_for_pane.return_value = "work"
        mill = ServerMill(
            tmux=tmux,
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        await mill.handle(_event_json("%3"))
        mill.clear_pending("work")
        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        data = json.loads(result)
        assert data["data"]["text"] == _FALLBACK_BADGE

    @staticmethod
    @pytest.mark.asyncio
    async def test_clear_pending_is_safe_for_unknown_session() -> None:
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        mill.clear_pending("nonexistent")  # must not raise


class TestDefaultSessionNameForCwd:
    @staticmethod
    @pytest.mark.asyncio
    async def test_uses_stem_for_cwd_when_no_callable_injected(tmp_path: Path) -> None:
        cwd = str(tmp_path)
        mill = ServerMill(tmux=_make_tmux(), socket_server=AsyncMock(), bus=_make_bus())

        ensure_msg = (
            f'{{"app": "vekna", "hook": "EnsureSession",'
            f' "payload": "", "meta": {{"cwd": "{cwd}"}}}}'
        )
        result = await mill.handle(ensure_msg)

        data = json.loads(result)
        assert data["data"]["session_name"] == stem_for_cwd(Path(cwd))


class TestHandleStatusBar:
    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_empty_text_when_no_pending() -> None:
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        data = json.loads(result)
        assert data["status"] == "ok"
        assert data["data"]["text"] == _FALLBACK_BADGE

    @staticmethod
    @pytest.mark.asyncio
    async def test_uses_session_mark_when_session_name_given() -> None:
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=_make_bus(),
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        result = await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "",'
            ' "meta": {"session_name": "vekna-work-abc123"}}'
        )

        data = json.loads(result)
        # Badge must reflect the session name, not the skull fallback.
        assert data["status"] == "ok"
        assert "vekna" not in data["data"]["text"].split("#[bg=default")[0].split()[-1]
        assert "work" in data["data"]["text"]

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_publish_status_bar_to_bus() -> None:
        bus = _make_bus()
        mill = ServerMill(
            tmux=_make_tmux(),
            socket_server=AsyncMock(),
            bus=bus,
            session_name_for_cwd=_SESSION_NAME_FOR_CWD,
        )

        await mill.handle(
            '{"app": "vekna", "hook": "StatusBar", "payload": "", "meta": {}}'
        )

        bus.publish.assert_not_called()
