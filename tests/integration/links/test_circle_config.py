from pathlib import Path

import pytest

from vekna.links.circle_config import ConfigLimits
from vekna.pacts.circle import DEFAULT_PROCESSES

_MINE = 8
_THE_PROJECT_S = 2
_CODING = 2


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


def _quiet(note: str) -> None:
    msg = f"nothing here should be said, and {note!r} was"
    raise AssertionError(msg)


@pytest.mark.usefixtures("config")
class TestProcesses:
    @staticmethod
    def test_nothing_configured_is_four(tmp_path: Path):
        assert (
            ConfigLimits(say=_quiet).processes(str(_project(tmp_path)))
            == DEFAULT_PROCESSES
        )

    @staticmethod
    def test_the_project_s_own_wins_over_the_user_s(config: Path, tmp_path: Path):
        config.write_text(f"[circle]\nprocesses = {_MINE}\n", encoding="utf-8")
        project = _project(tmp_path, f"[circle]\nprocesses = {_THE_PROJECT_S}\n")

        processes = ConfigLimits(say=_quiet).processes(str(project / "deep"))
        assert processes == _THE_PROJECT_S

    @staticmethod
    def test_the_user_s_counts_where_the_project_says_nothing(
        config: Path, tmp_path: Path
    ):
        config.write_text(f"[circle]\nprocesses = {_MINE}\n", encoding="utf-8")
        project = _project(tmp_path, "[rituals]\nfiles = []\n")

        assert ConfigLimits(say=_quiet).processes(str(project)) == _MINE

    @staticmethod
    def test_a_config_that_will_not_read_is_said_and_passed_over(tmp_path: Path):
        said: list[str] = []
        project = _project(tmp_path, "[circle]\nthreads = 2\n")

        assert (
            ConfigLimits(say=said.append).processes(str(project)) == DEFAULT_PROCESSES
        )
        assert len(said) == 1
        assert said[0].startswith(f"{project / '.vekna.toml'}: ")
        assert "threads" in said[0]


@pytest.mark.usefixtures("config")
class TestCoding:
    @staticmethod
    def test_no_limit_unless_the_user_says_one():
        assert ConfigLimits(say=_quiet).coding() is None

    @staticmethod
    def test_the_user_s_config_sets_it(config: Path):
        config.write_text(f"[circle]\ncoding = {_CODING}\n", encoding="utf-8")

        assert ConfigLimits(say=_quiet).coding() == _CODING

    @staticmethod
    def test_zero_is_refused(config: Path):
        said: list[str] = []
        config.write_text("[circle]\ncoding = 0\n", encoding="utf-8")

        assert ConfigLimits(say=said.append).coding() is None
        assert len(said) == 1
