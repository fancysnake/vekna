import os
from pathlib import Path

import pytest

from vekna.wire import default_runs_root, default_socket_path

_PERMISSION_BITS = 0o777
_PRIVATE = 0o700


@pytest.fixture(name="_no_environment")
def _cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEKNA_SOCKET", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)


class TestRunsRoot:
    @staticmethod
    def test_the_environment_names_it(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("VEKNA_RUNS", "/tmp/mine")

        assert default_runs_root() == Path("/tmp/mine")

    @staticmethod
    def test_the_session_state_directory_is_used_when_there_is_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.delenv("VEKNA_RUNS", raising=False)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))

        assert default_runs_root() == tmp_path / "vekna" / "runs"

    # A journal is history, not configuration: XDG puts it under the state
    # namespace, which is a different directory from `~/.config` on purpose.
    @staticmethod
    def test_otherwise_it_is_the_state_namespace(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("VEKNA_RUNS", raising=False)
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)

        assert default_runs_root().parts[-4:] == (".local", "state", "vekna", "runs")


class TestSocketPath:
    @staticmethod
    def test_the_environment_names_it(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("VEKNA_SOCKET", "/tmp/mine.sock")

        assert default_socket_path() == Path("/tmp/mine.sock")

    @staticmethod
    @pytest.mark.usefixtures("_no_environment")
    def test_the_session_runtime_directory_is_used_when_there_is_one(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        assert default_socket_path() == tmp_path / "vekna.sock"

    @staticmethod
    @pytest.mark.usefixtures("_no_environment")
    def test_otherwise_it_is_a_directory_of_this_users_own(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

        path = default_socket_path()

        assert path == tmp_path / f"vekna-{os.getuid()}" / "vekna.sock"
        assert path.parent.stat().st_mode & _PERMISSION_BITS == _PRIVATE

    # Somebody else's directory at the path vekna would use is somebody else
    # waiting for a cast to talk into.
    @staticmethod
    @pytest.mark.usefixtures("_no_environment")
    def test_a_directory_anybody_can_reach_is_refused(
        monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        shared = tmp_path / f"vekna-{os.getuid()}"
        shared.mkdir()
        shared.chmod(_PERMISSION_BITS)

        with pytest.raises(PermissionError, match="not this user's alone"):
            default_socket_path()
