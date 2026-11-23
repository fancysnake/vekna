import os
import socket
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from vekna.inits.cli import init_command

_SYSTEM = "/usr/local/bin:/usr/bin:/bin"
_NEEDS = "Error: `vekna service` needs systemd, and it is not answering: "


def _tool(path: Path, body: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


# Stands `systemctl` on PATH as a script that records what it was asked and
# calls the unit active once `active` exists, with a project's `vekna` beside
# it; home, the config directory and the socket are the test's own.
@pytest.fixture(name="home")
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "100% home"
    project = tmp_path / "project"
    _tool(
        project / "systemctl",
        f'echo "$@" >> "{tmp_path}/asked"\n'
        f'[ "$2" = is-active ] && [ ! -e "{tmp_path}/active" ] && exit 3\n'
        "exit 0\n",
    )
    _tool(project / "vekna")
    _tool(home / ".local" / "bin" / "vekna")
    monkeypatch.setenv("PATH", f"{project}{os.pathsep}{os.defpath}")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("VIRTUAL_ENV", str(project))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.chdir(project)
    return home


def _service(*args: str) -> Result:
    return CliRunner().invoke(init_command(), ["service", *args])


def _asked(home: Path) -> list[str]:
    asked = home.parent / "asked"
    return asked.read_text(encoding="utf-8").splitlines() if asked.exists() else []


def _unit(home: Path) -> Path:
    return home / ".config" / "systemd" / "user" / "vekna.service"


class TestServiceEnable:
    @staticmethod
    def test_it_writes_a_unit_of_the_user_s_own_vekna_run_from_home(home: Path):
        vekna = f"{home}/.local/bin/vekna"
        named = vekna.replace("%", "%%")
        tools = f"{home}/.local/bin:{home}/.local/share/mise/shims:{_SYSTEM}"

        ran = _service("enable")

        assert ran.exit_code == 0
        assert ran.output == (
            f"wrote {_unit(home)}: {vekna} starts at login"
            " — `vekna service start` for now\n"
        )
        assert _asked(home) == [
            "--user show-environment",
            "--user daemon-reload",
            "--user enable vekna.service",
        ]
        written = _unit(home).read_text(encoding="utf-8")
        assert f'ExecStart="{named}" "serve"\n' in written
        assert f'ExecStop="{named}" "stop"\n' in written
        assert "WorkingDirectory=%h\n" in written
        assert f'Environment="PATH={tools.replace("%", "%%")}"\n' in written
        assert str(home.parent / "project") not in written

    @staticmethod
    def test_a_vekna_only_a_project_has_is_refused(home: Path):
        (home / ".local" / "bin" / "vekna").unlink()

        ran = _service("enable")

        assert ran.exit_code == 1
        assert ran.output == (
            f"Error: no vekna of your own on {home}/.local/bin"
            f":{home}/.local/share/mise/shims:{_SYSTEM}: the service never runs"
            " a project's — `pipx install vekna`\n"
        )
        assert not _unit(home).exists()

    @staticmethod
    def test_a_unit_that_cannot_be_written_is_said(home: Path):
        (home / ".config").write_text("a file\n", encoding="utf-8")

        ran = _service("enable")

        assert ran.exit_code == 1
        assert ran.output.startswith("Error: could not write the unit: ")
        assert _asked(home) == ["--user show-environment"]


class TestServiceWithoutSystemd:
    @staticmethod
    def test_no_systemctl_fails_the_command(
        home: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PATH", str(home / "empty"))

        ran = _service("enable")

        assert ran.exit_code == 1
        assert ran.output == f"{_NEEDS}systemctl is not on PATH\n"
        assert not _unit(home).exists()

    @staticmethod
    def test_a_user_manager_that_does_not_answer_fails_the_command(home: Path):
        _tool(home.parent / "project" / "systemctl", "echo no user bus\nexit 1\n")

        ran = _service("stop")

        assert ran.exit_code == 1
        assert ran.output == (
            f"{_NEEDS}`systemctl --user show-environment` failed (1): no user bus\n"
        )


class TestServiceRuns:
    @staticmethod
    def test_start_without_a_unit_says_to_enable_first(home: Path):
        ran = _service("start")

        assert ran.exit_code == 1
        assert ran.output == (
            f"Error: no unit at {_unit(home)}: `vekna service enable` first\n"
        )
        assert _asked(home) == ["--user show-environment"]

    @staticmethod
    def test_start_starts_a_unit_that_is_not_running(home: Path):
        _service("enable")

        ran = _service("start")

        assert ran.exit_code == 0
        assert ran.output == "started the daemon under systemd\n"
        assert _asked(home)[3:] == [
            "--user show-environment",
            "--user is-active --quiet vekna.service",
            "--user start vekna.service",
        ]

    @staticmethod
    def test_start_leaves_a_running_unit_to_systemd(home: Path):
        _service("enable")
        (home.parent / "active").touch()

        ran = _service("start")

        assert ran.exit_code == 0
        assert _asked(home)[3:] == [
            "--user show-environment",
            "--user is-active --quiet vekna.service",
            "--user start vekna.service",
        ]

    @staticmethod
    def test_restart_restarts_it(home: Path):
        _service("enable")

        ran = _service("restart")

        assert ran.exit_code == 0
        assert ran.output == "restarted the daemon under systemd\n"
        assert _asked(home)[3:] == [
            "--user show-environment",
            "--user is-active --quiet vekna.service",
            "--user restart vekna.service",
        ]

    @staticmethod
    def test_stop_and_disable_ask_systemd(home: Path):
        stopped = _service("stop")
        disabled = _service("disable")

        assert (stopped.exit_code, stopped.output) == (0, "stopped the daemon\n")
        assert (disabled.exit_code, disabled.output) == (
            0,
            "the daemon no longer starts at login\n",
        )
        assert _asked(home) == [
            "--user show-environment",
            "--user stop vekna.service",
            "--user show-environment",
            "--user disable vekna.service",
        ]

    @staticmethod
    def test_a_systemctl_that_fails_is_said(home: Path):
        _tool(
            home.parent / "project" / "systemctl",
            '[ "$2" = stop ] && echo not loaded && exit 5\nexit 0\n',
        )

        ran = _service("stop")

        assert ran.exit_code == 1
        assert ran.output == (
            "Error: `systemctl --user stop vekna.service` failed (5): not loaded\n"
        )

    @staticmethod
    @pytest.mark.parametrize("verb", ["start", "restart"])
    def test_a_daemon_started_by_hand_is_left_alone(home: Path, verb: str):
        _service("enable")
        with socket.socket(socket.AF_UNIX) as by_hand:
            by_hand.bind(str(home.parent / "vekna.sock"))
            by_hand.listen()

            ran = _service(verb)

            probe, _ = by_hand.accept()
            with probe:
                sent = probe.recv(1024)

        assert ran.exit_code == 1
        assert ran.output == (
            "Error: a daemon started by hand is running, and the service leaves"
            " it alone: `vekna stop` when you are ready, then"
            f" `vekna service {verb}`\n"
        )
        assert sent == b""
        assert _asked(home)[3:] == [
            "--user show-environment",
            "--user is-active --quiet vekna.service",
        ]
