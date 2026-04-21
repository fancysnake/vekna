import math
import time
from pathlib import Path

import libtmux
from libtmux.common import tmux_cmd


class TmuxLink:
    def __init__(
        self,
        attention_style: str = "bg=red,fg=white,bold",
        conf_path: Path | None = None,
    ) -> None:
        self._server = libtmux.Server()
        self._attention_style = attention_style
        self._conf_path = conf_path

    def ensure_session(self, session_name: str, start_directory: str) -> None:
        if not self._server.has_session(session_name):
            self._server.new_session(
                session_name=session_name, start_directory=start_directory
            )
        if self._conf_path is not None:
            self._server.cmd("source-file", str(self._conf_path))

    def attach(self, session_name: str) -> None:
        self._server.attach_session(target_session=session_name)

    def select_pane(self, pane_id: str) -> None:
        self._server.cmd("select-window", "-t", pane_id)
        self._server.cmd("select-pane", "-t", pane_id)

    def window_id_for_pane(self, pane_id: str) -> str | None:
        return self._first_stdout_line(
            self._server.cmd(
                "display-message", "-p", "-t", pane_id, "-F", "#{window_id}"
            )
        )

    def session_name_for_pane(self, pane_id: str) -> str | None:
        return self._first_stdout_line(
            self._server.cmd(
                "display-message", "-p", "-t", pane_id, "-F", "#{session_name}"
            )
        )

    def active_window_id(self, session_name: str) -> str | None:
        return self._first_stdout_line(
            self._server.cmd(
                "display-message", "-p", "-t", session_name, "-F", "#{window_id}"
            )
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

    def display_message(self, text: str, session_name: str) -> None:
        self._server.cmd("display-message", "-t", session_name, text)

    def last_activity_seconds_ago(self, session_name: str) -> float:
        line = self._first_stdout_line(
            self._server.cmd(
                "display-message", "-p", "-t", session_name, "-F", "#{client_activity}"
            )
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
