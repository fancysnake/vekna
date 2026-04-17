import asyncio
import logging

from vekna.pacts.bus import HandlerProtocol
from vekna.pacts.notify import Event

_log = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    if exc := task.exception():
        _log.exception("Handler raised an exception", exc_info=exc)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], list[HandlerProtocol]] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def register(self, app: str, hook: str, handler: HandlerProtocol) -> None:
        self._handlers.setdefault((app, hook), []).append(handler)

    def publish(self, event: Event) -> None:
        for handler in self._handlers.get((event.app, event.hook), []):
            task = asyncio.create_task(handler(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            task.add_done_callback(_log_task_exception)
