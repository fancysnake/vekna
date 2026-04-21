import math
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from vekna.links.tmux import TmuxLink

_ACTIVITY_OFFSET = 10
_ACTIVITY_TOLERANCE = 2
_CONF_PATH = Path("/tmp/vekna.conf")


def _mock_cmd(stdout: list[str] | None = None) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout or []
    return result


def _make_link(
    attention_style: str = "bg=red", conf_path: Path | None = None
) -> tuple[TmuxLink, MagicMock]:
    with patch("vekna.links.tmux.libtmux") as mock_lib:
        mock_server = MagicMock()
        mock_lib.Server.return_value = mock_server
        link = TmuxLink(attention_style=attention_style, conf_path=conf_path)
        return link, mock_server


class TestEnsureSession:
    @staticmethod
    def test_creates_session_when_absent() -> None:
        link, server = _make_link()
        server.has_session.return_value = False

        link.ensure_session("work", "/home/user/project")

        server.new_session.assert_called_once_with(
            session_name="work", start_directory="/home/user/project"
        )

    @staticmethod
    def test_skips_creation_when_session_exists() -> None:
        link, server = _make_link()
        server.has_session.return_value = True

        link.ensure_session("work", "/home/user/project")

        server.new_session.assert_not_called()

    @staticmethod
    def test_sources_conf_file_when_conf_path_set() -> None:
        link, server = _make_link(conf_path=_CONF_PATH)
        server.has_session.return_value = False

        link.ensure_session("work", "/home/user/project")

        server.cmd.assert_called_once_with("source-file", str(_CONF_PATH))

    @staticmethod
    def test_sources_conf_file_even_when_session_already_exists() -> None:
        link, server = _make_link(conf_path=_CONF_PATH)
        server.has_session.return_value = True

        link.ensure_session("work", "/home/user/project")

        server.cmd.assert_called_once_with("source-file", str(_CONF_PATH))

    @staticmethod
    def test_does_not_source_conf_file_when_conf_path_is_none() -> None:
        link, server = _make_link(conf_path=None)
        server.has_session.return_value = False

        link.ensure_session("work", "/home/user/project")

        server.cmd.assert_not_called()


class TestAttach:
    @staticmethod
    def test_attaches_to_named_session() -> None:
        link, server = _make_link()

        link.attach("work")

        server.attach_session.assert_called_once_with(target_session="work")


class TestSelectPane:
    @staticmethod
    def test_selects_window_and_pane() -> None:
        link, server = _make_link()

        link.select_pane("%3")

        assert server.cmd.call_args_list == [
            call("select-window", "-t", "%3"),
            call("select-pane", "-t", "%3"),
        ]


class TestWindowIdForPane:
    @staticmethod
    def test_returns_window_id() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=["@2"])

        result = link.window_id_for_pane("%3")

        assert result == "@2"
        server.cmd.assert_called_once_with(
            "display-message", "-p", "-t", "%3", "-F", "#{window_id}"
        )

    @staticmethod
    def test_returns_none_when_no_stdout() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=[])

        assert link.window_id_for_pane("%3") is None

    @staticmethod
    def test_returns_none_for_whitespace_only_stdout() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=["   "])

        assert link.window_id_for_pane("%3") is None


class TestSessionNameForPane:
    @staticmethod
    def test_returns_session_name() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=["work"])

        result = link.session_name_for_pane("%3")

        assert result == "work"
        server.cmd.assert_called_once_with(
            "display-message", "-p", "-t", "%3", "-F", "#{session_name}"
        )

    @staticmethod
    def test_returns_none_when_no_stdout() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=[])

        assert link.session_name_for_pane("%3") is None


class TestActiveWindowId:
    @staticmethod
    def test_returns_active_window_id() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=["@1"])

        result = link.active_window_id("work")

        assert result == "@1"
        server.cmd.assert_called_once_with(
            "display-message", "-p", "-t", "work", "-F", "#{window_id}"
        )

    @staticmethod
    def test_returns_none_when_no_stdout() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=[])

        assert link.active_window_id("work") is None


class TestMarkWindow:
    @staticmethod
    def test_sets_window_status_style() -> None:
        link, server = _make_link(attention_style="bg=red,fg=white")

        link.mark_window("@3")

        server.cmd.assert_called_once_with(
            "set-window-option", "-t", "@3", "window-status-style", "bg=red,fg=white"
        )


class TestUnmarkWindow:
    @staticmethod
    def test_unsets_window_status_style() -> None:
        link, server = _make_link()

        link.unmark_window("@3")

        server.cmd.assert_called_once_with(
            "set-window-option", "-u", "-t", "@3", "window-status-style"
        )


class TestDisplayMessage:
    @staticmethod
    def test_sends_display_message_to_session() -> None:
        link, server = _make_link()

        link.display_message("something went wrong", "work")

        server.cmd.assert_called_once_with(
            "display-message", "-t", "work", "something went wrong"
        )


class TestLastActivitySecondsAgo:
    @staticmethod
    def test_returns_inf_when_no_stdout() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=[])

        result = link.last_activity_seconds_ago("work")

        assert result == math.inf

    @staticmethod
    def test_returns_inf_when_value_is_not_an_integer() -> None:
        link, server = _make_link()
        server.cmd.return_value = _mock_cmd(stdout=["bad"])

        result = link.last_activity_seconds_ago("work")

        assert result == math.inf

    @staticmethod
    def test_returns_elapsed_seconds_since_client_activity() -> None:
        link, server = _make_link()
        now = int(time.time())
        server.cmd.return_value = _mock_cmd(stdout=[str(now - _ACTIVITY_OFFSET)])

        result = link.last_activity_seconds_ago("work")

        assert _ACTIVITY_OFFSET - 1 < result < _ACTIVITY_OFFSET + _ACTIVITY_TOLERANCE
        server.cmd.assert_called_once_with(
            "display-message", "-p", "-t", "work", "-F", "#{client_activity}"
        )
