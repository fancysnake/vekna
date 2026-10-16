import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.links.spawner import Spawner
from vekna.pacts.circle import Exited
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

        exited = await spawn(_hello(project))

        assert exited == Exited(code=3, said="asked --resume c1")
        log = (tmp_path / "runs" / "c1" / "cast.log").read_text()
        assert log == f"{project}\nasked --resume c1\n"

    @staticmethod
    async def test_a_command_that_will_not_start_says_why(tmp_path: Path):
        spawn = Spawner(command=[str(tmp_path / "no-such")], runs=tmp_path / "runs")

        exited = await spawn(_hello(tmp_path))

        assert exited.code is None
        assert "no-such" in exited.said

    @staticmethod
    async def test_a_runs_root_it_cannot_write_says_why(tmp_path: Path):
        runs = tmp_path / "runs"
        runs.write_text("")
        spawn = Spawner(command=[sys.executable, "-c", _SAYS], runs=runs)

        exited = await spawn(_hello(tmp_path))

        assert exited.code is None
        assert str(runs) in exited.said
