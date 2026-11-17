import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from vekna.wire import (
    VERSION,
    DaemonVersion,
    daemon_refusal,
    daemon_version,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
    project_of,
    refused,
)

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

    @staticmethod
    def test_vekna_state_moves_the_state_root_and_the_runs_with_it(
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.delenv("VEKNA_RUNS")
        monkeypatch.setenv("VEKNA_STATE", "/tmp/second")

        assert default_state_root() == Path("/tmp/second")
        assert default_runs_root() == Path("/tmp/second/runs")


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

    @staticmethod
    def test_a_path_git_cannot_run_in_is_its_own(tmp_path: Path):
        file = tmp_path / "file"
        file.touch()

        assert asyncio.run(project_of(file)) == str(file.resolve())


_OTHER = f"{int(VERSION.partition('.')[0]) + 1}.0.0"


# A daemon that answers the version question with `said`, or hangs up on it the
# way one that predates the question does.
async def _daemon(path: Path, said: str | None) -> asyncio.Server:
    async def answer(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        await reader.readline()
        if said is not None:
            writer.write(encode_frame(DaemonVersion(version=said)))
            await writer.drain()
        writer.close()

    return await asyncio.start_unix_server(answer, path=str(path))


@pytest.mark.asyncio
class TestDaemonVersion:
    @staticmethod
    async def test_it_is_what_the_daemon_says(tmp_path: Path):
        path = tmp_path / "vekna.sock"
        server = await _daemon(path, "7.8.9")

        assert await daemon_version(path) == "7.8.9"
        server.close()

    @staticmethod
    async def test_a_daemon_that_hangs_up_has_none(tmp_path: Path):
        path = tmp_path / "vekna.sock"
        server = await _daemon(path, None)

        assert await daemon_version(path) is None
        server.close()

    @staticmethod
    async def test_a_daemon_that_never_answers_has_none(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("vekna.wire._links._PROBE_SECONDS", 0.05)
        path = tmp_path / "vekna.sock"

        async def silent(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
            await reader.read()
            writer.close()

        server = await asyncio.start_unix_server(silent, path=str(path))

        assert await daemon_version(path) is None
        server.close()

    @staticmethod
    async def test_nobody_listening_raises(tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            await daemon_version(tmp_path / "vekna.sock")


@pytest.mark.asyncio
class TestRefusal:
    @staticmethod
    async def test_nobody_listening_refuses_nothing(tmp_path: Path):
        assert await daemon_refusal(tmp_path / "vekna.sock") is None

    @staticmethod
    async def test_a_daemon_of_this_version_refuses_nothing(tmp_path: Path):
        path = tmp_path / "vekna.sock"
        server = await _daemon(path, VERSION)

        assert await daemon_refusal(path) is None
        server.close()

    @staticmethod
    async def test_another_major_version_is_refused_with_both_ways_out(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_STATE", str(tmp_path / "state"))
        path = tmp_path / "vekna.sock"
        major = VERSION.partition(".")[0]
        server = await _daemon(path, _OTHER)

        assert await daemon_refusal(path) == (
            f"the daemon on {path} is vekna {_OTHER}, and this is vekna {VERSION}:"
            " a daemon serves its own major version only.\n"
            "`vekna stop` ends it, and the next `vekna` starts this version's.\n"
            "To run this version beside it, export for every vekna that uses it:\n"
            f"  VEKNA_SOCKET={tmp_path}/vekna-{major}.sock"
            f" VEKNA_STATE={tmp_path}/state-{major}"
        )
        server.close()

    @staticmethod
    async def test_a_daemon_with_no_version_is_said_to_predate_the_check(
        tmp_path: Path,
    ):
        said = refused(tmp_path / "vekna.sock", None)

        assert said is not None
        assert said.startswith(
            f"the daemon on {tmp_path}/vekna.sock does not say its version, so it"
            f" predates this check, and this is vekna {VERSION}:"
        )
