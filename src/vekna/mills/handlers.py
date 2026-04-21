import asyncio
import itertools
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, ValidationError

from vekna.pacts.bus import App, EventBusProtocol, Hook
from vekna.pacts.notify import ERROR_PAYLOAD_INVALID_NOTIFICATION, Event
from vekna.pacts.tmux import TmuxLinkProtocol
from vekna.specs.attention import (
    ATTENTION_POLL_INTERVAL_SECONDS,
    IDLE_THRESHOLD_SECONDS,
)


class _ClaudeNotificationPayload(BaseModel):
    """Validates that the Claude hook payload is a JSON object.

    All fields are accepted and ignored.
    """

    model_config = ConfigDict(extra="ignore")


class DisplayErrorHandler:
    def __init__(self, tmux: TmuxLinkProtocol) -> None:
        self._tmux = tmux

    async def __call__(self, event: Event) -> None:
        if not (pane_id := event.meta.get("TMUX_PANE", "")):
            return
        if not (session_name := self._tmux.session_name_for_pane(pane_id)):
            return
        self._tmux.display_message(event.payload, session_name)


class ClaudeNotificationHandler:
    def __init__(self, bus: EventBusProtocol) -> None:
        self._bus = bus

    async def __call__(self, event: Event) -> None:
        try:
            _ClaudeNotificationPayload.model_validate_json(event.payload)
        except ValidationError:
            self._bus.publish(
                Event(
                    app=App.VEKNA,
                    hook=Hook.ERROR,
                    payload=ERROR_PAYLOAD_INVALID_NOTIFICATION,
                    meta=event.meta,
                )
            )
            return
        if not (pane_id := event.meta.get("TMUX_PANE", "")):
            return
        self._bus.publish(
            Event(app=App.VEKNA, hook=Hook.SELECT_PANE, payload=pane_id, meta={})
        )


class SelectPaneHandler:
    """Select the pane or mark its window, depending on user activity.

    When the user is idle the pane is switched to immediately.  When
    the user is active the source window is highlighted instead and
    cleared once the user navigates to it.  Call clear_marks_loop() as
    a background task to handle that cleanup.
    """

    def __init__(
        self,
        tmux: TmuxLinkProtocol,
        idle_threshold_seconds: float = IDLE_THRESHOLD_SECONDS,
        poll_interval_seconds: float = ATTENTION_POLL_INTERVAL_SECONDS,
        on_session_visited: Callable[[str], None] | None = None,
    ) -> None:
        self._tmux = tmux
        self._idle_threshold_seconds = idle_threshold_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._on_session_visited = on_session_visited
        self._marked_windows: dict[str, str] = {}  # window_id → session_name

    async def __call__(self, event: Event) -> None:
        pane_id = event.payload
        if (session_name := self._tmux.session_name_for_pane(pane_id)) is None:
            return
        if (
            self._tmux.last_activity_seconds_ago(session_name)
            < self._idle_threshold_seconds
        ):
            if (window_id := self._tmux.window_id_for_pane(pane_id)) is not None:
                self._tmux.mark_window(window_id)
                self._marked_windows[window_id] = session_name
        else:
            self._tmux.select_pane(pane_id)
            if self._on_session_visited is not None:
                self._on_session_visited(session_name)

    async def clear_marks_loop(self) -> None:
        """Poll and unmark windows as the user navigates to them."""
        for _ in itertools.count():
            await asyncio.sleep(self._poll_interval_seconds)
            self.clear_marks_once()

    def clear_marks_once(self) -> None:
        for window_id, session_name in list(self._marked_windows.items()):
            if self._tmux.active_window_id(session_name) == window_id:
                del self._marked_windows[window_id]
                self._tmux.unmark_window(window_id)
                if self._on_session_visited is not None:
                    self._on_session_visited(session_name)
