import asyncio
import os
import socket
import tempfile
import time
from collections.abc import Callable, Coroutine
from pathlib import Path

from click import Group

from vekna.gates.cli.click.command import ClickGate
from vekna.links.socket_client import SocketClientLink
from vekna.links.socket_server import SocketServerLink
from vekna.links.tmux import TmuxLink
from vekna.mills.bus import EventBus
from vekna.mills.handlers import (
    ClaudeNotificationHandler,
    DisplayErrorHandler,
    SelectPaneHandler,
)
from vekna.mills.notify import NotifyClientMill
from vekna.mills.server import ServerMill
from vekna.pacts.bus import App, Hook
from vekna.pacts.notify import NotifyClientMillProtocol
from vekna.pacts.server import ServerMillProtocol

_TMUX_CONF_PATH: Path = Path(__file__).parent.parent / "conf" / "tmux.conf"


def daemon_socket_path() -> str:
    return str(Path(tempfile.gettempdir()) / f"vekna-{os.getuid()}.sock")


_DAEMON_START_TIMEOUT_SECONDS = 3.0
_DAEMON_POLL_INTERVAL_SECONDS = 0.1
_DAEMON_DID_NOT_START = "daemon did not start"


def _build_server_mill() -> ServerMillProtocol:
    tmux_link = TmuxLink(conf_path=_TMUX_CONF_PATH)
    socket_server_link = SocketServerLink(socket_path=daemon_socket_path())
    bus = EventBus()
    background: list[Callable[[], Coroutine[None, None, None]]] = []
    server_mill = ServerMill(
        tmux=tmux_link, socket_server=socket_server_link, bus=bus, background=background
    )
    select_handler = SelectPaneHandler(
        tmux_link, on_session_visited=server_mill.clear_pending
    )
    background.append(select_handler.clear_marks_loop)
    bus.register(App.VEKNA, Hook.SELECT_PANE, select_handler)
    bus.register(App.VEKNA, Hook.ERROR, DisplayErrorHandler(tmux_link))
    bus.register(App.CLAUDE, Hook.NOTIFICATION, ClaudeNotificationHandler(bus))
    return server_mill


def _build_notify_client_mill() -> NotifyClientMillProtocol:
    socket_client_link = SocketClientLink(socket_path=daemon_socket_path())
    return NotifyClientMill(socket_client=socket_client_link)


def _socket_is_alive(path: str) -> bool:
    alive = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(path)
            alive = True
    except OSError:
        pass
    return alive


def _spawn_daemon() -> None:  # pragma: no cover
    """Fork and run the server mill as a detached background daemon."""
    if os.fork() != 0:
        return  # parent returns immediately; child is adopted by init
    # Child: become a new session leader and redirect stdio
    os.setsid()
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd_num in (0, 1, 2):
        os.dup2(devnull, fd_num)
    os.close(devnull)
    asyncio.run(_build_server_mill().run())
    os._exit(0)


def ensure_daemon_running(spawn: Callable[[], None] = _spawn_daemon) -> None:
    socket_path = daemon_socket_path()
    if _socket_is_alive(socket_path):
        return
    spawn()
    iterations = round(_DAEMON_START_TIMEOUT_SECONDS / _DAEMON_POLL_INTERVAL_SECONDS)
    for _ in range(iterations):
        time.sleep(_DAEMON_POLL_INTERVAL_SECONDS)
        if _socket_is_alive(socket_path):
            return
    raise RuntimeError(_DAEMON_DID_NOT_START)


def init_command() -> Group:
    click_gate = ClickGate(
        server_mill_factory=_build_server_mill,
        notify_client_mill_factory=_build_notify_client_mill,
        ensure_daemon=ensure_daemon_running,
    )
    return click_gate.build_group()


def run() -> None:
    init_command()()  # pragma: no cover


if __name__ == "__main__":
    run()  # pragma: no cover
