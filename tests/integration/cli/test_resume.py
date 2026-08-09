import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command
from vekna.lexicon._inits import main
from vekna.lexicon._links.resume import default_runs_root
from vekna.links.journal import Journal
from vekna.wire import CastHello, RiteFinished, RiteStarted, encode_frame

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_USAGE_EXIT = 2

# Each step records what it did into a file, so a resumed cast can be asked what
# it re-ran and what it took off the journal instead.
_RITUALS = textwrap.dedent("""
    from pathlib import Path

    from pydantic import BaseModel

    from vekna.folio.shell import shell
    from vekna.lexicon import Transition, done, goto, ritual, step


    class State(BaseModel):
        left: int


    class Report(BaseModel):
        said: str


    @step
    async def work(state: State) -> Transition:
        result = await shell("echo ran-" + str(state.left))
        Path("ran.log").open("a").write(result.stdout)
        if state.left == 0:
            return done(Report(said=result.stdout.strip()))
        return goto(work, State(left=state.left - 1))


    @ritual("job")
    async def job(components: State) -> Transition:
        return goto(work, State(left=components.left))
    """)


def _journalled(project: Path, runs: Path, cast_id: str) -> None:
    journal = Journal(runs)
    journal.record(
        CastHello(
            cast_id=cast_id,
            project_root=str(project),
            ritual="job",
            components={"left": 1},
            started_at=_WHEN,
        )
    )


def _rite(
    cast_id: str, *, rite_id: str, name: str, category: Literal["step", "medium"]
) -> RiteStarted:
    return RiteStarted(
        cast_id=cast_id,
        rite_id=rite_id,
        parent_id=None,
        name=name,
        category=category,
        started_at=_WHEN,
    )


@pytest.fixture(name="project")
def _project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / "rituals.py").write_text(_RITUALS)
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "nothing.sock"))
    monkeypatch.chdir(project)
    return project


def _record_an_interrupted_cast(project: Path, runs: Path) -> str:
    cast_id = "c1"
    _journalled(project, runs, cast_id)
    journal = Journal(runs)
    # The first pass got through one shell rite and was interrupted inside the
    # step that opened the second.
    journal.record(_rite(cast_id, rite_id="r1", name="work", category="step"))
    journal.record(_rite(cast_id, rite_id="r2", name="shell", category="medium"))
    journal.record(
        RiteFinished(
            cast_id=cast_id,
            rite_id="r2",
            status="ok",
            result={"stdout": "from-the-journal\n", "stderr": "", "exit_code": 0},
            finished_at=_WHEN,
        )
    )
    return cast_id


class TestResume:
    @staticmethod
    def test_a_rite_that_finished_is_not_run_again(project: Path, tmp_path: Path):
        cast_id = _record_an_interrupted_cast(project, tmp_path / "runs")

        assert main(["--resume", cast_id]) == 0

        # The first shell rite came off the journal; only the second ran.
        assert (project / "ran.log").read_text() == "from-the-journal\nran-0\n"

    @staticmethod
    def test_it_ends_where_the_ritual_says_not_where_the_journal_stops(
        project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        cast_id = _record_an_interrupted_cast(project, tmp_path / "runs")

        main(["--resume", cast_id])

        assert '"said":"ran-0"' in capsys.readouterr().out

    @staticmethod
    def test_a_ledger_that_stops_matching_runs_live_from_there(
        project: Path, tmp_path: Path
    ):
        runs = tmp_path / "runs"
        cast_id = "c2"
        _journalled(project, runs, cast_id)
        journal = Journal(runs)
        journal.record(_rite(cast_id, rite_id="r1", name="work", category="step"))
        # The recorded rite at r2 was a different medium: this cast did not walk
        # the path that journal describes, so nothing of it is replayed.
        journal.record(_rite(cast_id, rite_id="r2", name="coding", category="medium"))
        journal.record(
            RiteFinished(
                cast_id=cast_id,
                rite_id="r2",
                status="ok",
                result={"stdout": "never-used\n", "stderr": "", "exit_code": 0},
                finished_at=_WHEN,
            )
        )

        assert main(["--resume", cast_id]) == 0

        assert (project / "ran.log").read_text() == "ran-1\nran-0\n"

    @staticmethod
    def test_an_unfinished_rite_is_run_rather_than_replayed(
        project: Path, tmp_path: Path
    ):
        runs = tmp_path / "runs"
        cast_id = "c3"
        _journalled(project, runs, cast_id)
        journal = Journal(runs)
        journal.record(_rite(cast_id, rite_id="r1", name="work", category="step"))
        # Interrupted mid-rite: started, never finished.
        journal.record(_rite(cast_id, rite_id="r2", name="shell", category="medium"))

        assert main(["--resume", cast_id]) == 0

        assert (project / "ran.log").read_text() == "ran-1\nran-0\n"

    @staticmethod
    @pytest.mark.usefixtures("project")
    def test_a_cast_with_no_journal_says_so():
        assert main(["--resume", "never-happened"]) == _USAGE_EXIT

    @staticmethod
    @pytest.mark.usefixtures("project")
    def test_resume_needs_a_cast_id():
        assert main(["--resume"]) == _USAGE_EXIT


class TestResumeCommand:
    @staticmethod
    @pytest.mark.usefixtures("project")
    def test_it_refuses_a_cast_it_has_no_record_of(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))

        result = CliRunner().invoke(init_command(), ["casts", "resume", "nope"])

        assert result.exit_code == 1
        assert "no cast 'nope' in the journal" in result.output

    # The whole way round: a real process, in the recorded directory.
    @staticmethod
    def test_it_spawns_a_cast_in_the_directory_the_first_one_ran_in(
        project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        cast_id = _record_an_interrupted_cast(project, tmp_path / "runs")
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(init_command(), ["casts", "resume", cast_id])

        assert result.exit_code == 0
        assert (project / "ran.log").read_text() == "from-the-journal\nran-0\n"


class TestWhereTheJournalLives:
    @staticmethod
    def test_the_environment_names_it(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("VEKNA_RUNS", "/tmp/mine")

        assert default_runs_root() == Path("/tmp/mine")

    @staticmethod
    def test_otherwise_it_is_the_config_namespace(monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("VEKNA_RUNS", raising=False)

        assert default_runs_root().parts[-3:] == (".config", "vekna", "runs")

    # A run directory with no event log is a cast the daemon heard say hello and
    # nothing else. There is nothing to replay, and that is not an error.
    @staticmethod
    def test_a_run_with_no_events_replays_nothing(project: Path, tmp_path: Path):
        cast_id = "c4"
        _journalled(project, tmp_path / "runs", cast_id)
        (tmp_path / "runs" / cast_id / "events.jsonl").unlink()

        assert main(["--resume", cast_id]) == 0

        assert (project / "ran.log").read_text() == "ran-1\nran-0\n"


class TestFramesOnDisk:
    @staticmethod
    def test_the_reader_skips_a_blank_line(project: Path, tmp_path: Path):
        cast_id = _record_an_interrupted_cast(project, tmp_path / "runs")
        events = tmp_path / "runs" / cast_id / "events.jsonl"
        with events.open("ab") as log:
            log.write(b"\n")
            log.write(
                encode_frame(_rite(cast_id, rite_id="r9", name="x", category="step"))
            )

        assert main(["--resume", cast_id]) == 0
