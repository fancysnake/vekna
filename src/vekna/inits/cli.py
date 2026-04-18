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
from vekna.specs import (
    ATTENTION_POLL_INTERVAL_SECONDS,
    ATTENTION_WINDOW_STATUS_STYLE,
    IDLE_THRESHOLD_SECONDS,
    paths_for,
    stem_for_cwd,
    stem_from_tmux_env,
)


def _build_server_mill() -> ServerMillProtocol:
    stem = stem_for_cwd(Path.cwd())
    tmux_socket_name, tmux_session_name, unix_socket_path = paths_for(stem)
    tmux_link = TmuxLink(
        socket_name=tmux_socket_name,
        session_name=tmux_session_name,
        attention_style=ATTENTION_WINDOW_STATUS_STYLE,
    )
    socket_server_link = SocketServerLink(socket_path=unix_socket_path)
    bus = EventBus()
    select_handler = SelectPaneHandler(
        tmux_link, IDLE_THRESHOLD_SECONDS, ATTENTION_POLL_INTERVAL_SECONDS
    )
    bus.register(App.VEKNA, Hook.SELECT_PANE, select_handler)
    bus.register(App.VEKNA, Hook.ERROR, DisplayErrorHandler(tmux_link))
    bus.register(App.CLAUDE, Hook.NOTIFICATION, ClaudeNotificationHandler(bus))
    return ServerMill(
        tmux=tmux_link,
        socket_server=socket_server_link,
        bus=bus,
        background=[select_handler.clear_marks_loop],
    )


def _build_notify_client_mill(tmux_env: str) -> NotifyClientMillProtocol:
    stem = stem_from_tmux_env(tmux_env)
    _, _, unix_socket_path = paths_for(stem)
    socket_client_link = SocketClientLink(socket_path=unix_socket_path)
    return NotifyClientMill(socket_client=socket_client_link)


def init_command() -> Group:
    click_gate = ClickGate(
        server_mill_factory=_build_server_mill,
        notify_client_mill_factory=_build_notify_client_mill,
    )
    return click_gate.build_group()


def run() -> None:
    init_command()()  # pragma: no cover


if __name__ == "__main__":
    run()  # pragma: no cover
