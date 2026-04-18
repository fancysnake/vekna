import asyncio
import itertools

from pydantic import BaseModel, ConfigDict, ValidationError

from vekna.pacts.bus import App, EventBusProtocol, Hook
from vekna.pacts.notify import ERROR_PAYLOAD_INVALID_NOTIFICATION, Event
from vekna.pacts.tmux import TmuxLinkProtocol


class _ClaudeNotificationPayload(BaseModel):
    """Validates that the Claude hook payload is a JSON object.

    All fields are accepted and ignored.
    """

    model_config = ConfigDict(extra="ignore")


class DisplayErrorHandler:
    def __init__(self, tmux: TmuxLinkProtocol) -> None:
        self._tmux = tmux

    async def __call__(self, event: Event) -> None:
        self._tmux.display_message(event.payload)


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
                    meta={},
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
        idle_threshold_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        self._tmux = tmux
        self._idle_threshold_seconds = idle_threshold_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._marked_windows: set[str] = set()

    async def __call__(self, event: Event) -> None:
        if self._tmux.last_activity_seconds_ago() < self._idle_threshold_seconds:
            if (window_id := self._tmux.window_id_for_pane(event.payload)) is not None:
                self._tmux.mark_window(window_id)
                self._marked_windows.add(window_id)
        else:
            self._tmux.select_pane(event.payload)

    async def clear_marks_loop(self) -> None:
        """Poll and unmark windows as the user navigates to them."""
        for _ in itertools.count():
            await asyncio.sleep(self._poll_interval_seconds)
            self.clear_marks_once()

    def clear_marks_once(self) -> None:
        active = self._tmux.active_window_id()
        if active is not None and active in self._marked_windows:
            self._marked_windows.discard(active)
            self._tmux.unmark_window(active)
