import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Sequence

from pydantic import ValidationError

from vekna.pacts.bus import EventBusProtocol
from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE, Event
from vekna.pacts.socket import SocketServerLinkProtocol
from vekna.pacts.tmux import TmuxLinkProtocol


class ServerMill:
    def __init__(
        self,
        tmux: TmuxLinkProtocol,
        socket_server: SocketServerLinkProtocol,
        bus: EventBusProtocol,
        background: Sequence[Callable[[], Coroutine[None, None, None]]] = (),
    ) -> None:
        self._tmux = tmux
        self._socket_server = socket_server
        self._bus = bus
        self._background = background

    async def run(self) -> None:
        self._tmux.ensure_session()
        await self._socket_server.start(self.handle)
        bg_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(coro()) for coro in self._background
        ]
        await asyncio.sleep(0)  # let background tasks reach their first await
        try:
            await asyncio.to_thread(self._tmux.attach)
        finally:
            for task in bg_tasks:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await self._bus.drain()
            await self._socket_server.stop()

    async def handle(self, message: str) -> str:
        try:
            event = Event.model_validate_json(message)
        except ValidationError:
            return ERROR_RESPONSE_INVALID
        self._bus.publish(event)
        return OK_RESPONSE
