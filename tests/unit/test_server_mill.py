import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from vekna.mills.server import ServerMill
from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE


def _make_tmux(
    *,
    idle: float | None = None,
    window_id: str | None = "@1",
    active_window: str | None = None,
) -> MagicMock:
    tmux = MagicMock()
    tmux.seconds_since_last_keystroke.return_value = idle
    tmux.window_id_for_pane.return_value = window_id
    tmux.active_window_id.return_value = active_window
    return tmux


def _make_mill(tmux: MagicMock, socket_server: AsyncMock) -> ServerMill:
    return ServerMill(
        tmux=tmux,
        socket_server=socket_server,
        idle_threshold_seconds=3.0,
        clear_poll_interval_seconds=1.0,
    )


class TestRun:
    @staticmethod
    @pytest.mark.asyncio
    async def test_starts_socket_server_before_attach() -> None:
        tmux = _make_tmux()
        socket_server = AsyncMock()
        call_order: list[str] = []
        socket_server.start.side_effect = lambda _h: call_order.append("start")
        tmux.attach.side_effect = lambda: call_order.append("attach")
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        assert call_order == ["start", "attach"]

    @staticmethod
    @pytest.mark.asyncio
    async def test_stops_socket_server_after_attach() -> None:
        tmux = _make_tmux()
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        socket_server.stop.assert_called_once_with()

    @staticmethod
    @pytest.mark.asyncio
    async def test_stops_socket_server_on_attach_failure() -> None:
        tmux = _make_tmux()
        tmux.attach.side_effect = RuntimeError("tmux crashed")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        with contextlib.suppress(RuntimeError):
            await mill.run()

        socket_server.stop.assert_called_once_with()

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_start_server_if_ensure_session_fails() -> None:
        tmux = _make_tmux()
        tmux.ensure_session.side_effect = RuntimeError("tmux not found")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        with contextlib.suppress(RuntimeError):
            await mill.run()

        socket_server.start.assert_not_called()
        tmux.attach.assert_not_called()


class TestHandle:
    @staticmethod
    @pytest.mark.asyncio
    async def test_calls_select_pane_with_pane_id() -> None:
        tmux = _make_tmux(idle=None)
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler('{"pane_id": "%3"}')

        tmux.select_pane.assert_called_once_with("%3")
        tmux.mark_window.assert_not_called()
        assert result == OK_RESPONSE

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_json() -> None:
        tmux = _make_tmux()
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler("not json")

        tmux.select_pane.assert_not_called()
        tmux.mark_window.assert_not_called()
        assert result == ERROR_RESPONSE_INVALID

    @staticmethod
    @pytest.mark.asyncio
    async def test_switches_pane_when_user_is_idle() -> None:
        tmux = _make_tmux(idle=10.0)
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler('{"pane_id": "%3"}')

        tmux.select_pane.assert_called_once_with("%3")
        tmux.mark_window.assert_not_called()
        assert result == OK_RESPONSE

    @staticmethod
    @pytest.mark.asyncio
    async def test_marks_window_when_user_is_typing() -> None:
        tmux = _make_tmux(idle=1.0, window_id="@5")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler('{"pane_id": "%3"}')

        tmux.select_pane.assert_not_called()
        tmux.window_id_for_pane.assert_called_once_with("%3")
        tmux.mark_window.assert_called_once_with("@5")
        assert result == OK_RESPONSE

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_mark_when_window_id_unknown() -> None:
        tmux = _make_tmux(idle=1.0, window_id=None)
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler('{"pane_id": "%3"}')

        tmux.select_pane.assert_not_called()
        tmux.mark_window.assert_not_called()
        assert result == OK_RESPONSE


class TestClearMarksOnce:
    @staticmethod
    @pytest.mark.asyncio
    async def test_unmarks_window_when_it_becomes_active() -> None:
        tmux = _make_tmux(idle=1.0, window_id="@5", active_window="@5")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()
        handler = socket_server.start.call_args[0][0]
        await handler('{"pane_id": "%3"}')

        mill.clear_marks_once()

        tmux.unmark_window.assert_called_once_with("@5")

    @staticmethod
    @pytest.mark.asyncio
    async def test_ignores_unmarked_active_window() -> None:
        tmux = _make_tmux(idle=1.0, window_id="@5", active_window="@7")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()
        handler = socket_server.start.call_args[0][0]
        await handler('{"pane_id": "%3"}')

        mill.clear_marks_once()

        tmux.unmark_window.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_handles_unknown_active_window() -> None:
        tmux = _make_tmux(idle=1.0, window_id="@5", active_window=None)
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()
        handler = socket_server.start.call_args[0][0]
        await handler('{"pane_id": "%3"}')

        mill.clear_marks_once()

        tmux.unmark_window.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_unmarks_only_once_then_stops() -> None:
        tmux = _make_tmux(idle=1.0, window_id="@5", active_window="@5")
        socket_server = AsyncMock()
        mill = _make_mill(tmux, socket_server)

        await mill.run()
        handler = socket_server.start.call_args[0][0]
        await handler('{"pane_id": "%3"}')

        mill.clear_marks_once()
        mill.clear_marks_once()

        tmux.unmark_window.assert_called_once_with("@5")
