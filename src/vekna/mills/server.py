import asyncio
import contextlib
import itertools
from typing import TYPE_CHECKING

from pydantic import ValidationError

from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE, NotifyRequest

if TYPE_CHECKING:
    from vekna.pacts.socket import SocketServerLinkProtocol
    from vekna.pacts.tmux import TmuxLinkProtocol


class ServerMill:
    def __init__(
        self,
        tmux: TmuxLinkProtocol,
        socket_server: SocketServerLinkProtocol,
        idle_threshold_seconds: float,
        clear_poll_interval_seconds: float,
    ) -> None:
        self._tmux = tmux
        self._socket_server = socket_server
        self._idle_threshold_seconds = idle_threshold_seconds
        self._clear_poll_interval_seconds = clear_poll_interval_seconds
        self._marked_windows: set[str] = set()

    async def run(self) -> None:
        self._tmux.ensure_session()
        await self._socket_server.start(self._handle)
        clear_task = asyncio.create_task(self._clear_marks_loop())
        try:
            await asyncio.to_thread(self._tmux.attach)
        finally:
            clear_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await clear_task
            await self._socket_server.stop()

    async def _handle(self, message: str) -> str:
        try:
            request = NotifyRequest.model_validate_json(message)
        except ValidationError:
            return ERROR_RESPONSE_INVALID
        idle = self._tmux.seconds_since_last_keystroke()
        if idle is not None and idle < self._idle_threshold_seconds:
            window_id = self._tmux.window_id_for_pane(request.pane_id)
            if window_id is not None:
                self._tmux.mark_window(window_id)
                self._marked_windows.add(window_id)
            return OK_RESPONSE
        self._tmux.select_pane(request.pane_id)
        return OK_RESPONSE

    async def _clear_marks_loop(self) -> None:
        for _ in itertools.count():
            await asyncio.sleep(self._clear_poll_interval_seconds)
            self.clear_marks_once()

    def clear_marks_once(self) -> None:
        active = self._tmux.active_window_id()
        if active is not None and active in self._marked_windows:
            self._tmux.unmark_window(active)
            self._marked_windows.discard(active)
