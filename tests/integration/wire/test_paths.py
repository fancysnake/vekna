import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from vekna.wire import default_runs_root, default_socket_path, project_of

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


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


# Git itself, in a directory nothing above can claim: what the cast and the
# window agree on is whatever it answers.
@pytest.fixture(name="_no_repository_above")
def _ceiling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


@pytest.mark.usefixtures("_no_repository_above")
class TestProject:
    @staticmethod
    def test_a_checkout_and_its_worktree_are_one_project(tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        _git("init", "-q", cwd=repo)
        _git(
            "-c",
            "user.name=vekna",
            "-c",
            "user.email=vekna@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "root",
            cwd=repo,
        )
        _git("worktree", "add", "-q", str(tmp_path / "wt"), cwd=repo)
        common = str((repo / ".git").resolve())

        assert asyncio.run(project_of(repo)) == common
        assert asyncio.run(project_of(tmp_path / "wt")) == common

    @staticmethod
    def test_a_directory_in_no_repository_is_its_own(tmp_path: Path):
        assert asyncio.run(project_of(tmp_path)) == str(tmp_path.resolve())
