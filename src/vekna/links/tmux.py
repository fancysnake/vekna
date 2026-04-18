import math
import time

import libtmux
from libtmux.common import tmux_cmd


class TmuxLink:
    def __init__(
        self, socket_name: str, session_name: str, attention_style: str
    ) -> None:
        self._server = libtmux.Server(socket_name=socket_name)
        self._session_name = session_name
        self._attention_style = attention_style

    def ensure_session(self) -> None:
        if not self._server.has_session(self._session_name):
            self._server.new_session(session_name=self._session_name)

    def attach(self) -> None:
        self._server.attach_session(target_session=self._session_name)

    def select_pane(self, pane_id: str) -> None:
        self._server.cmd("select-window", "-t", pane_id)
        self._server.cmd("select-pane", "-t", pane_id)

    def window_id_for_pane(self, pane_id: str) -> str | None:
        return self._first_stdout_line(
            self._server.cmd(
                "display-message", "-p", "-t", pane_id, "-F", "#{window_id}"
            )
        )

    def active_window_id(self) -> str | None:
        return self._first_stdout_line(
            self._server.cmd("display-message", "-p", "-F", "#{window_id}")
        )

    def mark_window(self, window_id: str) -> None:
        self._server.cmd(
            "set-window-option",
            "-t",
            window_id,
            "window-status-style",
            self._attention_style,
        )

    def unmark_window(self, window_id: str) -> None:
        self._server.cmd(
            "set-window-option", "-u", "-t", window_id, "window-status-style"
        )

    def display_message(self, text: str) -> None:
        self._server.cmd("display-message", "-t", self._session_name, text)

    def last_activity_seconds_ago(self) -> float:
        line = self._first_stdout_line(
            self._server.cmd("display-message", "-p", "-F", "#{client_activity}")
        )
        if line is None:
            return math.inf
        try:
            return time.time() - int(line)
        except ValueError:
            return math.inf

    @staticmethod
    def _first_stdout_line(result: tmux_cmd) -> str | None:
        if not (stdout := result.stdout):
            return None
        line = stdout[0].strip()
        return line or None
