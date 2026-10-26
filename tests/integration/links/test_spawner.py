import asyncio
import os
import signal
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.links.spawner import Spawner, signal_pid
from vekna.pacts.circle import Exited, Spawned
from vekna.wire import CastHello

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _hello(project_root: Path) -> CastHello:
    return CastHello(
        cast_id="c1",
        project_root=str(project_root),
        project=str(project_root),
        ritual="nap",
        components={},
        started_at=_WHEN,
        wired=True,
    )


# Stands in for `vekna cast --wired`: prints where it ran and what it was asked
# to resume, then exits with a code of its choosing.
_SAYS = "import os,sys;print(os.getcwd());print('asked',*sys.argv[1:]);sys.exit(3)"


@pytest.mark.asyncio
class TestSpawner:
    @staticmethod
    async def test_the_cast_runs_in_its_tree_and_its_output_is_logged(tmp_path: Path):
        project = tmp_path / "proj"
        project.mkdir()
        spawn = Spawner(command=[sys.executable, "-c", _SAYS], runs=tmp_path / "runs")

        exited = await spawn(_hello(project), None)

        assert exited == Exited(code=3, said="asked --resume c1")
        log = (tmp_path / "runs" / "c1" / "cast.log").read_text()
        assert log == f"{project}\nasked --resume c1\n"

    @staticmethod
    async def test_a_leased_cast_runs_in_the_tree(tmp_path: Path):
        tree = tmp_path / "tree"
        tree.mkdir()
        spawn = Spawner(command=[sys.executable, "-c", _SAYS], runs=tmp_path / "runs")

        exited = await spawn(_hello(tmp_path), str(tree))

        assert exited == Exited(code=3, said="asked --resume c1")
        log = (tmp_path / "runs" / "c1" / "cast.log").read_text()
        assert log == f"{tree}\nasked --resume c1\n"

    # What the cast reads back is what a daemon started under it would read.
    @staticmethod
    async def test_a_running_cast_is_left_behind_until_it_exits(tmp_path: Path):
        runs, tree = tmp_path / "runs", tmp_path / "tree"
        tree.mkdir()
        reads = textwrap.dedent("""
            import os
            import sys
            from pathlib import Path

            from vekna.links.spawner import Spawner

            left = Spawner(command=[], runs=Path(sys.argv[1])).left_behind()
            print(left[0].pid == os.getpid(), left[0].tree)
            """)
        spawn = Spawner(command=[sys.executable, "-c", reads, str(runs)], runs=runs)

        exited = await spawn(_hello(tmp_path), str(tree))

        assert exited == Exited(code=0, said=f"True {tree}")
        assert not Spawner(command=[], runs=runs).left_behind()
        assert not (runs / "c1" / "spawned.json").exists()

    # A daemon killed under its casts leaves its marks; one whose process is
    # gone is cleared rather than held.
    @staticmethod
    async def test_a_cast_whose_process_is_gone_is_not_left_behind(tmp_path: Path):
        runs = tmp_path / "runs"
        gone = await asyncio.create_subprocess_exec(sys.executable, "-c", "")
        await gone.wait()
        mark = runs / "c1" / "spawned.json"
        mark.parent.mkdir(parents=True)
        mark.write_text(
            f'{{"cast_id":"c1","pid":{os.getpid()},"project":"p","tree":null}}'
        )
        dead = runs / "c2" / "spawned.json"
        dead.parent.mkdir()
        dead.write_text(
            f'{{"cast_id":"c2","pid":{gone.pid},"project":"p","tree":null}}'
        )

        left = Spawner(command=[], runs=runs).left_behind()

        assert left == [Spawned(cast_id="c1", pid=os.getpid(), project="p", tree=None)]
        assert not dead.exists()

    # Zero would ask after the daemon's own process group, and a pid past the
    # platform's range will not reach the kernel at all.
    @pytest.mark.parametrize("pid", [0, -1, 2**64])
    @staticmethod
    async def test_a_pid_no_cast_can_have_is_not_left_behind(tmp_path: Path, pid: int):
        mark = tmp_path / "runs" / "c1" / "spawned.json"
        mark.parent.mkdir(parents=True)
        mark.write_text(f'{{"cast_id":"c1","pid":{pid},"project":"p","tree":null}}')

        left = Spawner(command=[], runs=tmp_path / "runs").left_behind()

        assert not left
        assert not mark.exists()

    # Another user's process is still running; only root may signal it, so the
    # refusal is faked rather than left to whoever runs the test.
    @staticmethod
    async def test_a_cast_it_may_not_signal_is_left_behind(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        mark = tmp_path / "runs" / "c1" / "spawned.json"
        mark.parent.mkdir(parents=True)
        mark.write_text('{"cast_id":"c1","pid":4242,"project":"p","tree":null}')
        signalled: list[tuple[int, int]] = []

        def kill(pid: int, sig: int) -> None:
            signalled.append((pid, sig))
            raise PermissionError(1, "Operation not permitted")

        monkeypatch.setattr(os, "kill", kill)

        left = Spawner(command=[], runs=tmp_path / "runs").left_behind()

        assert left == [Spawned(cast_id="c1", pid=4242, project="p", tree=None)]
        assert signalled == [(4242, 0)]
        assert mark.exists()

    # A daemon stopping cancels its wait; the cast it was waiting on runs on.
    @staticmethod
    async def test_a_cancelled_wait_leaves_the_cast_behind(tmp_path: Path):
        runs = tmp_path / "runs"
        mark = runs / "c1" / "spawned.json"
        sleeps = "import time;time.sleep(60)"
        spawn = Spawner(command=[sys.executable, "-c", sleeps], runs=runs)

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1):
                await spawn(_hello(tmp_path), None)

        left = Spawner(command=[], runs=runs).left_behind()
        os.kill(left[0].pid, signal.SIGKILL)
        assert [spawned.cast_id for spawned in left] == ["c1"]
        assert mark.exists()

    # A mark that is a directory refuses the write, for root as much as anyone.
    @staticmethod
    async def test_a_cast_that_cannot_be_marked_does_not_run(tmp_path: Path):
        runs = tmp_path / "runs"
        (runs / "c1" / "spawned.json").mkdir(parents=True)
        sleeps = "import time;time.sleep(60)"
        spawn = Spawner(command=[sys.executable, "-c", sleeps], runs=runs)

        async with asyncio.timeout(10):
            exited = await spawn(_hello(tmp_path), None)

        assert exited.code is None
        assert "spawned.json" in exited.said

    @staticmethod
    async def test_a_torn_mark_is_cleared(tmp_path: Path):
        mark = tmp_path / "runs" / "c1" / "spawned.json"
        mark.parent.mkdir(parents=True)
        mark.write_text('{"cast_id":"c1","pi')

        left = Spawner(command=[], runs=tmp_path / "runs").left_behind()

        assert not left
        assert not mark.exists()

    @staticmethod
    async def test_a_command_that_will_not_start_says_why(tmp_path: Path):
        spawn = Spawner(command=[str(tmp_path / "no-such")], runs=tmp_path / "runs")

        exited = await spawn(_hello(tmp_path), None)

        assert exited.code is None
        assert "no-such" in exited.said

    # A cast that swaps its own log for a directory is the way a log that will
    # not read back looks from here, for root as much as for anyone else.
    @staticmethod
    async def test_a_log_that_will_not_read_back_says_why(tmp_path: Path):
        log = tmp_path / "runs" / "c1" / "cast.log"
        swaps = f"import os,sys;os.remove({str(log)!r});os.mkdir({str(log)!r})"
        spawn = Spawner(command=[sys.executable, "-c", swaps], runs=tmp_path / "runs")

        exited = await spawn(_hello(tmp_path), None)

        assert exited.code == 0
        assert str(log) in exited.said

    @staticmethod
    async def test_a_runs_root_it_cannot_write_says_why(tmp_path: Path):
        runs = tmp_path / "runs"
        runs.write_text("")
        spawn = Spawner(command=[sys.executable, "-c", _SAYS], runs=runs)

        exited = await spawn(_hello(tmp_path), None)

        assert exited.code is None
        assert str(runs) in exited.said


class TestSignalPid:
    @staticmethod
    def test_a_running_process_is_signalled():
        sleeps = [sys.executable, "-c", "import time;time.sleep(60)"]
        with subprocess.Popen(sleeps) as child:
            sent = signal_pid(child.pid, signal.SIGTERM)

            assert sent is True
            assert child.wait(timeout=10) == -signal.SIGTERM

    @staticmethod
    def test_a_process_already_gone_is_not():
        with subprocess.Popen([sys.executable, "-c", ""]) as child:
            child.wait(timeout=10)

        assert signal_pid(child.pid, signal.SIGTERM) is False

    @staticmethod
    @pytest.mark.parametrize("pid", [0, -1])
    def test_a_pid_naming_a_group_is_not(pid: int):
        assert signal_pid(pid, signal.SIGTERM) is False
