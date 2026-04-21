import asyncio
import contextlib
import hashlib
from collections.abc import Callable, Coroutine, Sequence
from pathlib import Path

from pydantic import ValidationError

from vekna.pacts.bus import App, EventBusProtocol, Hook
from vekna.pacts.notify import ERROR_RESPONSE_INVALID, OK_RESPONSE, Event
from vekna.pacts.socket import Response, SocketServerLinkProtocol
from vekna.pacts.tmux import TmuxLinkProtocol
from vekna.specs.session import STEM_DIGEST_LENGTH, stem_for_cwd

# Each tuple is (emoji, tmux 256-colour background, tmux 256-colour foreground).
# Emojis follow necromancer / dark-fantasy iconography;
# bg colours are distinct dark shades; fg colours contrast with each bg.
_SESSION_MARKS: list[tuple[str, int, int]] = [
    ("☠️", 88, 231),  # dark red bg          → white fg
    ("⚔️", 52, 220),  # dark crimson bg       → bright yellow fg
    ("⚰️", 94, 45),  # dark amber-brown bg   → bright cyan fg
    ("⛓️", 23, 214),  # dark teal bg          → orange fg
    ("✋", 130, 159),  # dark orange-brown bg  → light cyan fg
    ("🌙", 17, 226),  # dark navy bg          → yellow fg
    ("🏰", 58, 207),  # dark olive bg         → bright pink fg
    ("🐍", 28, 228),  # dark forest green bg  → light yellow fg
    ("👁️", 53, 154),  # dark burgundy-purple bg → yellow-green fg
    ("👑", 100, 51),  # dark olive-gold bg    → bright cyan fg
    ("💀", 22, 231),  # deep forest green bg  → white fg
    ("📖", 54, 82),  # dark magenta bg       → bright green fg
    ("📜", 64, 201),  # dark yellow-green bg  → bright magenta fg
    ("🔮", 55, 226),  # dark violet bg        → yellow fg
    ("🕯️", 18, 214),  # midnight blue bg      → orange fg
    ("🕷️", 29, 220),  # dark cyan-green bg    → yellow fg
    ("🕸️", 57, 154),  # dark blue-violet bg   → yellow-green fg
    ("🗝️", 24, 214),  # dark slate blue bg    → orange fg
    ("🗡️", 91, 159),  # dark violet-purple bg → light cyan fg
    ("🦴", 95, 51),  # dark rose-brown bg    → bright cyan fg
    ("🧙\u200d♂️", 56, 220),  # dark blue-violet bg   → yellow fg
    ("🧠", 90, 46),  # dark magenta-purple bg → bright green fg
    ("🧿", 89, 159),  # dark magenta-red bg   → light cyan fg
    ("🩸", 96, 51),  # dark mauve bg         → bright cyan fg
    ("🪦", 30, 228),  # dark cyan bg          → light yellow fg
]


def _mark_for_session(session_name: str) -> tuple[str, int, int]:
    index = int(hashlib.sha256(session_name.encode()).hexdigest(), 16)
    return _SESSION_MARKS[index % len(_SESSION_MARKS)]


def _pretty_name(session_name: str) -> str:
    prefix = "vekna-"
    suffix_len = 1 + STEM_DIGEST_LENGTH  # "-" + digest
    if session_name.startswith(prefix) and len(session_name) > len(prefix) + suffix_len:
        return session_name[len(prefix) : -suffix_len]
    return session_name


def _default_session_name_for_cwd(cwd: str) -> str:
    return stem_for_cwd(Path(cwd))


class ServerMill:
    def __init__(
        self,
        tmux: TmuxLinkProtocol,
        socket_server: SocketServerLinkProtocol,
        bus: EventBusProtocol,
        session_name_for_cwd: Callable[[str], str] = _default_session_name_for_cwd,
        background: Sequence[Callable[[], Coroutine[None, None, None]]] = (),
    ) -> None:
        self._tmux = tmux
        self._socket_server = socket_server
        self._bus = bus
        self._session_name_for_cwd = session_name_for_cwd
        self._background = background
        self._pending: dict[str, int] = {}  # session_name → notification count
        self._stop_event: asyncio.Event | None = None

    async def run(self) -> None:
        self._stop_event = asyncio.Event()
        await self._socket_server.start(self.handle)
        bg_tasks: list[asyncio.Task[None]] = [
            asyncio.create_task(coro()) for coro in self._background
        ]
        try:
            await asyncio.sleep(0)  # let background tasks reach their first await
            await self._stop_event.wait()
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
            return ERROR_RESPONSE_INVALID.model_dump_json()
        if event.app == App.VEKNA and event.hook == Hook.ENSURE_SESSION:
            return self._handle_ensure_session(event)
        if event.app == App.VEKNA and event.hook == Hook.STATUS_BAR:
            return self._handle_status_bar(event)
        if (
            event.app == App.CLAUDE
            and event.hook == Hook.NOTIFICATION
            and (pane_id := event.meta.get("TMUX_PANE", ""))
            and (session_name := self._tmux.session_name_for_pane(pane_id))
        ):
            self._pending[session_name] = self._pending.get(session_name, 0) + 1
        self._bus.publish(event)
        return OK_RESPONSE.model_dump_json()

    def _handle_ensure_session(self, event: Event) -> str:
        cwd = event.meta["cwd"]
        session_name = self._session_name_for_cwd(cwd)
        self._tmux.ensure_session(session_name, cwd)
        self._pending[session_name] = 0
        return Response(
            status="ok", data={"session_name": session_name}
        ).model_dump_json()

    def clear_pending(self, session_name: str) -> None:
        self._pending.pop(session_name, None)

    def _handle_status_bar(self, event: Event) -> str:
        session_name = event.meta.get("session_name", "")
        emoji, bg_colour, fg_colour = (
            _mark_for_session(session_name) if session_name else _SESSION_MARKS[0]
        )
        label = _pretty_name(session_name) if session_name else "vekna"
        pending_parts = [
            f"{_pretty_name(name)}({count})"
            for name, count in self._pending.items()
            if count > 0
        ]
        badge = (
            f"#[bg=colour{bg_colour},fg=colour{fg_colour}] {emoji} {label} "
            "#[bg=default,fg=colour245]"
        )
        text = badge + (" ".join(pending_parts) if pending_parts else "")
        return Response(status="ok", data={"text": text}).model_dump_json()
