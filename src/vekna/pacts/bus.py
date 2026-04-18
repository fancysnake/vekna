from enum import Enum
from typing import Protocol

from vekna.pacts.notify import Event


class App(str, Enum):
    VEKNA = "vekna"
    CLAUDE = "claude"


class Hook(str, Enum):
    SELECT_PANE = "SelectPane"
    ERROR = "Error"
    NOTIFICATION = "Notification"


class HandlerProtocol(Protocol):
    async def __call__(self, event: Event) -> None: ...


class EventBusProtocol(Protocol):
    def register(self, app: App, hook: Hook, handler: HandlerProtocol) -> None: ...

    def publish(self, event: Event) -> None: ...

    async def drain(self) -> None: ...
