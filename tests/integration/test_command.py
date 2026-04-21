from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command


@pytest.fixture
def _clean_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX_PANE", raising=False)


@pytest.mark.usefixtures("_clean_tmux_env")
class TestVekna:
    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.request", new_callable=AsyncMock)
    @patch("vekna.inits.cli.ensure_daemon_running")
    @patch("os.execvp")
    def test_ensures_daemon_and_attaches(
        execvp_mock, ensure_mock, request_mock
    ) -> None:
        response = MagicMock()
        response.data = {"session_name": "vekna-foo-abc123"}
        request_mock.return_value = response
        runner = CliRunner()

        result = runner.invoke(init_command())

        assert result.exit_code == 0
        ensure_mock.assert_called_once_with()
        request_mock.assert_called_once()
        execvp_mock.assert_called_once_with(
            "tmux", ["tmux", "attach-session", "-t", "vekna-foo-abc123"]
        )

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.request", new_callable=AsyncMock)
    @patch("vekna.inits.cli.ensure_daemon_running")
    @patch("os.execvp")
    def test_sends_ensure_session_with_cwd(
        execvp_mock, ensure_mock, request_mock
    ) -> None:
        response = MagicMock()
        response.data = {"session_name": "vekna-foo-abc123"}
        request_mock.return_value = response
        runner = CliRunner()

        runner.invoke(init_command())

        ensure_mock.assert_called_once_with()
        execvp_mock.assert_called_once()
        call_event = request_mock.call_args[0][0]
        assert call_event.app == "vekna"
        assert call_event.hook == "EnsureSession"
        assert "cwd" in call_event.meta


@pytest.mark.usefixtures("_clean_tmux_env")
class TestDaemon:
    @staticmethod
    @patch("vekna.mills.server.ServerMill.run")
    def test_invokes_server_mill_run(run_mock) -> None:
        runner = CliRunner()

        result = runner.invoke(init_command(), ["daemon"])

        assert result.exit_code == 0
        run_mock.assert_called_once_with()


@pytest.mark.usefixtures("_clean_tmux_env")
class TestNotify:
    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_invokes_notify_with_app_hook_and_pane(
        notify_mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(
            init_command(), ["notify", "--app", "claude", "--hook", "Notification"]
        )

        assert result.exit_code == 0
        notify_mock.assert_called_once_with(
            app="claude", hook="Notification", payload="", meta={"TMUX_PANE": "%7"}
        )

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_reads_stdin_as_payload(
        notify_mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(
            init_command(),
            ["notify", "--app", "claude", "--hook", "Notification"],
            input='{"title": "done"}',
        )

        assert result.exit_code == 0
        notify_mock.assert_called_once_with(
            app="claude",
            hook="Notification",
            payload='{"title": "done"}',
            meta={"TMUX_PANE": "%7"},
        )

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_fails_without_tmux_pane(notify_mock) -> None:
        runner = CliRunner()

        result = runner.invoke(
            init_command(), ["notify", "--app", "claude", "--hook", "Notification"]
        )

        assert result.exit_code != 0
        assert "TMUX_PANE must be set" in result.output
        notify_mock.assert_not_called()

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_fails_without_app(notify_mock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(init_command(), ["notify", "--hook", "Notification"])

        assert result.exit_code != 0
        notify_mock.assert_not_called()

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_fails_without_hook(notify_mock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(init_command(), ["notify", "--app", "claude"])

        assert result.exit_code != 0
        notify_mock.assert_not_called()


@pytest.mark.usefixtures("_clean_tmux_env")
class TestStatusBar:
    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.request", new_callable=AsyncMock)
    def test_prints_pending_text(request_mock) -> None:
        response = MagicMock()
        response.data = {"text": "work(2)"}
        request_mock.return_value = response
        runner = CliRunner()

        result = runner.invoke(init_command(), ["status-bar"])

        assert result.exit_code == 0
        assert "work(2)" in result.output

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.request", new_callable=AsyncMock)
    def test_sends_status_bar_event(request_mock) -> None:
        response = MagicMock()
        response.data = {"text": ""}
        request_mock.return_value = response
        runner = CliRunner()

        runner.invoke(init_command(), ["status-bar"])

        call_event = request_mock.call_args[0][0]
        assert call_event.app == "vekna"
        assert call_event.hook == "StatusBar"

    @staticmethod
    @patch(
        "vekna.mills.notify.NotifyClientMill.request",
        side_effect=OSError("connection refused"),
    )
    def test_exits_silently_if_daemon_not_running(request_mock) -> None:
        runner = CliRunner()

        result = runner.invoke(init_command(), ["status-bar"])

        request_mock.assert_called_once()
        assert result.exit_code == 0
        assert not result.output
