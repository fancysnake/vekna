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
