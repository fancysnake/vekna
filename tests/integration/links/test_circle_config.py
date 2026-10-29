import logging
from pathlib import Path

import pytest

from vekna.links.circle_config import ConfigLimits
from vekna.pacts.circle import DEFAULT_PROCESSES, DEFAULT_WORKTREES

_MINE = 8
_THE_PROJECT_S = 2
_CODING = 2
_THE_PROJECT_S_TREES = 3


@pytest.fixture(name="config")
def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


def _project(tmp_path: Path, toml: str | None = None) -> Path:
    project = tmp_path / "proj"
    (project / "deep").mkdir(parents=True)
    if toml is not None:
        (project / ".vekna.toml").write_text(toml, encoding="utf-8")
    return project


def _warned(caplog: pytest.LogCaptureFixture) -> list[str]:
    assert {record.levelno for record in caplog.records} == {logging.WARNING}
    return [record.getMessage() for record in caplog.records]


@pytest.mark.usefixtures("config")
class TestProcesses:
    @staticmethod
    def test_nothing_configured_is_four(tmp_path: Path):
        assert ConfigLimits().processes(str(_project(tmp_path))) == DEFAULT_PROCESSES

    @staticmethod
    def test_the_project_s_own_wins_over_the_user_s(config: Path, tmp_path: Path):
        config.write_text(f"[circle]\nprocesses = {_MINE}\n", encoding="utf-8")
        project = _project(tmp_path, f"[circle]\nprocesses = {_THE_PROJECT_S}\n")

        processes = ConfigLimits().processes(str(project / "deep"))
        assert processes == _THE_PROJECT_S

    @staticmethod
    def test_the_user_s_counts_where_the_project_says_nothing(
        config: Path, tmp_path: Path
    ):
        config.write_text(f"[circle]\nprocesses = {_MINE}\n", encoding="utf-8")
        project = _project(tmp_path, "[rituals]\nfiles = []\n")

        assert ConfigLimits().processes(str(project)) == _MINE

    @staticmethod
    def test_a_config_that_will_not_read_is_said_and_passed_over(
        tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        project = _project(tmp_path, "[circle]\nthreads = 2\n")

        assert ConfigLimits().processes(str(project)) == DEFAULT_PROCESSES
        [said] = _warned(caplog)
        assert said.startswith(f"{project / '.vekna.toml'}: ")
        assert "threads" in said


@pytest.mark.usefixtures("config")
class TestCoding:
    @staticmethod
    def test_no_limit_unless_the_user_says_one():
        assert ConfigLimits().coding() is None

    @staticmethod
    def test_the_user_s_config_sets_it(config: Path):
        config.write_text(f"[circle]\ncoding = {_CODING}\n", encoding="utf-8")

        assert ConfigLimits().coding() == _CODING

    @staticmethod
    def test_zero_is_refused(config: Path, caplog: pytest.LogCaptureFixture):
        config.write_text("[circle]\ncoding = 0\n", encoding="utf-8")

        assert ConfigLimits().coding() is None
        assert _warned(caplog) == [
            (
                f"{config}: circle.coding: Input should be greater than 0"
                " — [circle] ignored"
            )
        ]


@pytest.mark.usefixtures("config")
class TestWorktrees:
    @staticmethod
    def test_nothing_configured_is_two_trees_and_no_prepare(tmp_path: Path):
        limits = ConfigLimits()
        project = str(_project(tmp_path))

        assert limits.worktrees(project) == DEFAULT_WORKTREES
        assert limits.prepare(project) is None

    @staticmethod
    def test_the_project_s_own_wins_over_the_user_s(config: Path, tmp_path: Path):
        config.write_text(
            '[circle]\nworktrees = 5\nprepare = "mine"\n', encoding="utf-8"
        )
        project = _project(
            tmp_path,
            f'[circle]\nworktrees = {_THE_PROJECT_S_TREES}\nprepare = "ours"\n',
        )
        limits = ConfigLimits()

        assert limits.worktrees(str(project / "deep")) == _THE_PROJECT_S_TREES
        assert limits.prepare(str(project / "deep")) == "ours"

    @staticmethod
    def test_the_user_s_counts_where_the_project_says_nothing(
        config: Path, tmp_path: Path
    ):
        config.write_text('[circle]\nprepare = "mine"\n', encoding="utf-8")

        assert ConfigLimits().prepare(str(_project(tmp_path))) == "mine"

    @staticmethod
    def test_zero_is_refused(
        config: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        config.write_text("[circle]\nworktrees = 0\n", encoding="utf-8")

        limits = ConfigLimits()

        assert limits.worktrees(str(_project(tmp_path))) == DEFAULT_WORKTREES
        assert len(_warned(caplog)) == 1
