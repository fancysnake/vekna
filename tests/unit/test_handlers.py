import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from vekna.mills.handlers import (
    ClaudeNotificationHandler,
    DisplayErrorHandler,
    SelectPaneHandler,
)
from vekna.pacts.notify import ERROR_PAYLOAD_INVALID_NOTIFICATION, Event
from vekna.specs import IDLE_THRESHOLD_SECONDS

_THRESHOLD = IDLE_THRESHOLD_SECONDS
_POLL = 1.0


def _notification_event(pane_id: str = "%3", payload: str = "{}") -> Event:
    return Event(
        app="claude", hook="Notification", payload=payload, meta={"TMUX_PANE": pane_id}
    )


def _select_pane_event(pane_id: str = "%3") -> Event:
    return Event(app="vekna", hook="SelectPane", payload=pane_id, meta={})


def _make_select_pane_handler(tmux: MagicMock) -> SelectPaneHandler:
    return SelectPaneHandler(
        tmux=tmux, idle_threshold_seconds=_THRESHOLD, poll_interval_seconds=_POLL
    )


class TestDisplayErrorHandler:
    @staticmethod
    @pytest.mark.asyncio
    async def test_displays_payload_as_message() -> None:
        tmux = MagicMock()
        handler = DisplayErrorHandler(tmux)
        event = Event(
            app="vekna", hook="Error", payload="something went wrong", meta={}
        )

        await handler(event)

        tmux.display_message.assert_called_once_with("something went wrong")


class TestClaudeNotificationHandler:
    @staticmethod
    @pytest.mark.asyncio
    async def test_publishes_select_pane_event_with_pane_id() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)

        await handler(_notification_event(pane_id="%5"))

        bus.publish.assert_called_once_with(
            Event(app="vekna", hook="SelectPane", payload="%5", meta={})
        )

    @staticmethod
    @pytest.mark.asyncio
    async def test_ignores_extra_payload_fields() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)
        payload = json.dumps({"title": "done", "unknown_future_field": 42})

        await handler(_notification_event(payload=payload))

        bus.publish.assert_called_once_with(
            Event(app="vekna", hook="SelectPane", payload="%3", meta={})
        )

    @staticmethod
    @pytest.mark.asyncio
    async def test_publishes_error_event_on_invalid_payload() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)
        event = Event(
            app="claude",
            hook="Notification",
            payload="not json",
            meta={"TMUX_PANE": "%3"},
        )

        await handler(event)

        bus.publish.assert_called_once_with(
            Event(
                app="vekna",
                hook="Error",
                payload=ERROR_PAYLOAD_INVALID_NOTIFICATION,
                meta={},
            )
        )

    @staticmethod
    @pytest.mark.asyncio
    async def test_publishes_error_event_on_empty_payload() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)
        event = Event(
            app="claude", hook="Notification", payload="", meta={"TMUX_PANE": "%3"}
        )

        await handler(event)

        bus.publish.assert_called_once_with(
            Event(
                app="vekna",
                hook="Error",
                payload=ERROR_PAYLOAD_INVALID_NOTIFICATION,
                meta={},
            )
        )

    @staticmethod
    @pytest.mark.asyncio
    async def test_skips_event_when_tmux_pane_missing() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)
        event = Event(app="claude", hook="Notification", payload="{}", meta={})

        await handler(event)

        bus.publish.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_skips_event_when_tmux_pane_empty() -> None:
        bus = MagicMock()
        handler = ClaudeNotificationHandler(bus)
        event = Event(
            app="claude", hook="Notification", payload="{}", meta={"TMUX_PANE": ""}
        )

        await handler(event)

        bus.publish.assert_not_called()


class TestSelectPaneHandler:
    @staticmethod
    @pytest.mark.asyncio
    async def test_selects_pane_when_user_is_idle() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%7"))

        tmux.select_pane.assert_called_once_with("%7")

    @staticmethod
    @pytest.mark.asyncio
    async def test_selects_pane_when_well_past_threshold() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD + 10.0
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%7"))

        tmux.select_pane.assert_called_once_with("%7")

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_select_pane_when_user_is_active() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = None
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%7"))

        tmux.select_pane.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_checks_activity_each_call() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.side_effect = [
            _THRESHOLD - 0.1,  # first call: active, mark
            _THRESHOLD + 1.0,  # second call: idle, switch
        ]
        tmux.window_id_for_pane.return_value = None
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%7"))
        await handler(_select_pane_event("%7"))

        tmux.select_pane.assert_called_once_with("%7")
        assert tmux.last_activity_seconds_ago.call_args_list == [call(), call()]

    @staticmethod
    @pytest.mark.asyncio
    async def test_marks_window_when_user_is_active() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = "@5"
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))

        tmux.mark_window.assert_called_once_with("@5")

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_mark_when_user_is_idle() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))

        tmux.mark_window.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_does_not_mark_when_window_id_unknown() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = None
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))

        tmux.mark_window.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_activity_checked_once_per_event() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = "@5"
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))

        tmux.last_activity_seconds_ago.assert_called_once()


class TestSelectPaneHandlerClearMarks:
    @staticmethod
    @pytest.mark.asyncio
    async def test_unmarks_window_when_it_becomes_active() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = "@5"
        tmux.active_window_id.return_value = "@5"
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))
        handler.clear_marks_once()

        tmux.unmark_window.assert_called_once_with("@5")

    @staticmethod
    def test_does_not_unmark_when_active_window_not_marked() -> None:
        tmux = MagicMock()
        tmux.active_window_id.return_value = "@7"
        handler = _make_select_pane_handler(tmux)

        handler.clear_marks_once()

        tmux.unmark_window.assert_not_called()

    @staticmethod
    @pytest.mark.asyncio
    async def test_clear_marks_loop_exits_when_iterator_exhausted() -> None:
        tmux = MagicMock()
        handler = _make_select_pane_handler(tmux)

        with patch("vekna.mills.handlers.itertools.count", return_value=iter([])):
            await handler.clear_marks_loop()

    @staticmethod
    @pytest.mark.asyncio
    async def test_clear_marks_loop_sleeps_and_calls_clear_marks_once() -> None:
        tmux = MagicMock()
        tmux.active_window_id.return_value = None
        handler = _make_select_pane_handler(tmux)
        sleep_mock = AsyncMock(side_effect=[None, asyncio.CancelledError])

        with (
            patch("vekna.mills.handlers.asyncio.sleep", sleep_mock),
            pytest.raises(asyncio.CancelledError),
        ):
            await handler.clear_marks_loop()

        assert sleep_mock.call_args_list == [call(_POLL), call(_POLL)]

    @staticmethod
    @pytest.mark.asyncio
    async def test_unmarks_only_once() -> None:
        tmux = MagicMock()
        tmux.last_activity_seconds_ago.return_value = _THRESHOLD - 0.1
        tmux.window_id_for_pane.return_value = "@5"
        tmux.active_window_id.return_value = "@5"
        handler = _make_select_pane_handler(tmux)

        await handler(_select_pane_event("%3"))
        handler.clear_marks_once()
        handler.clear_marks_once()

        tmux.unmark_window.assert_called_once_with("@5")
