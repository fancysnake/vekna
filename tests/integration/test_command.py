from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command

_TMUX_ENV = "/tmp/tmux-1000/vekna-foo-a3f1c2,12345,$0"


@pytest.fixture
def _clean_tmux_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)


@pytest.mark.usefixtures("_clean_tmux_env")
class TestVekna:
    @staticmethod
    @patch("vekna.mills.server.ServerMill.run")
    def test_invokes_server_mill_run(run_mock) -> None:
        runner = CliRunner()

        result = runner.invoke(init_command())

        assert result.exit_code == 0
        run_mock.assert_called_once_with()


@pytest.mark.usefixtures("_clean_tmux_env")
class TestNotify:
    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_invokes_notify_with_pane_id(
        notify_mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TMUX", _TMUX_ENV)
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(init_command(), ["notify"])

        assert result.exit_code == 0
        notify_mock.assert_called_once_with("%7")

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_fails_without_tmux_pane(
        notify_mock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TMUX", _TMUX_ENV)
        runner = CliRunner()

        result = runner.invoke(init_command(), ["notify"])

        assert result.exit_code != 0
        assert "TMUX and TMUX_PANE must be set" in result.output
        notify_mock.assert_not_called()

    @staticmethod
    @patch("vekna.mills.notify.NotifyClientMill.notify", new_callable=AsyncMock)
    def test_fails_without_tmux(notify_mock, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TMUX_PANE", "%7")
        runner = CliRunner()

        result = runner.invoke(init_command(), ["notify"])

        assert result.exit_code != 0
        assert "TMUX and TMUX_PANE must be set" in result.output
        notify_mock.assert_not_called()
