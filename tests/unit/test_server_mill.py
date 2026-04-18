import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from vekna.mills.server import ServerMill
from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE, Event


def _make_tmux() -> MagicMock:
    return MagicMock()


def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.drain = AsyncMock()
    return bus


def _make_mill(tmux: MagicMock, socket_server: AsyncMock) -> ServerMill:
    return ServerMill(tmux=tmux, socket_server=socket_server, bus=_make_bus())


def _event_json(pane_id: str = "%3") -> str:
    return (
        f'{{"app": "claude", "hook": "Notification",'
        f' "payload": "", "meta": {{"TMUX_PANE": "{pane_id}"}}}}'
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

    @staticmethod
    @pytest.mark.asyncio
    async def test_cancels_background_tasks_after_attach() -> None:
        tmux = _make_tmux()
        socket_server = AsyncMock()
        cancelled: list[bool] = []

        async def bg() -> None:
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        mill = ServerMill(
            tmux=tmux, socket_server=socket_server, bus=_make_bus(), background=[bg]
        )

        await mill.run()

        assert cancelled == [True]

    @staticmethod
    @pytest.mark.asyncio
    async def test_drains_bus_after_attach() -> None:
        bus = _make_bus()
        mill = ServerMill(tmux=_make_tmux(), socket_server=AsyncMock(), bus=bus)

        await mill.run()

        bus.drain.assert_awaited_once()


class TestHandle:
    @staticmethod
    @pytest.mark.asyncio
    async def test_publishes_event_to_bus() -> None:
        bus = _make_bus()
        socket_server = AsyncMock()
        mill = ServerMill(tmux=_make_tmux(), socket_server=socket_server, bus=bus)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler(_event_json("%3"))

        bus.publish.assert_called_once_with(
            Event(
                app="claude", hook="Notification", payload="", meta={"TMUX_PANE": "%3"}
            )
        )
        assert result == OK_RESPONSE

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_ok_for_valid_event() -> None:
        socket_server = AsyncMock()
        mill = _make_mill(_make_tmux(), socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler(_event_json())

        assert result == OK_RESPONSE

    @staticmethod
    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_json() -> None:
        socket_server = AsyncMock()
        mill = _make_mill(_make_tmux(), socket_server)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        result = await handler("not json")

        assert result == ERROR_RESPONSE_INVALID

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_publish_on_invalid_message() -> None:
        bus = _make_bus()
        socket_server = AsyncMock()
        mill = ServerMill(tmux=_make_tmux(), socket_server=socket_server, bus=bus)

        await mill.run()

        handler = socket_server.start.call_args[0][0]
        await handler("not json")

        bus.publish.assert_not_called()
