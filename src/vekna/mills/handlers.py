import asyncio
import itertools

from pydantic import BaseModel, ConfigDict

from vekna.pacts.bus import EventBusProtocol
from vekna.pacts.notify import Event
from vekna.pacts.tmux import TmuxLinkProtocol


class _ClaudeNotificationPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ClaudeNotificationHandler:
    def __init__(self, bus: EventBusProtocol) -> None:
        self._bus = bus

    async def __call__(self, event: Event) -> None:
        _ClaudeNotificationPayload.model_validate_json(event.payload)
        if not (pane_id := event.meta.get("TMUX_PANE", "")):
            return
        self._bus.publish(
            Event(app="vekna", hook="SelectPane", payload=pane_id, meta={})
        )


class SelectPaneHandler:
    def __init__(self, tmux: TmuxLinkProtocol, idle_threshold_seconds: float) -> None:
        self._tmux = tmux
        self._idle_threshold_seconds = idle_threshold_seconds

    async def __call__(self, event: Event) -> None:
        if self._tmux.last_activity_seconds_ago() < self._idle_threshold_seconds:
            return
        self._tmux.select_pane(event.payload)


class MarkWindowHandler:
    """Mark the originating window red when the user is active.

    Registered for ("vekna", "SelectPane") alongside SelectPaneHandler.
    When the user has been active recently the pane switch is suppressed
    and this handler highlights the source window instead.  Call
    clear_marks_loop() as a background task to remove the mark once
    the user navigates to the window.
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
        if self._tmux.last_activity_seconds_ago() >= self._idle_threshold_seconds:
            return
        if (window_id := self._tmux.window_id_for_pane(event.payload)) is not None:
            self._tmux.mark_window(window_id)
            self._marked_windows.add(window_id)

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
