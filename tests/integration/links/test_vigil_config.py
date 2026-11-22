import logging
from pathlib import Path

import pytest

from vekna.links.vigil_config import ConfigVigils, vigil_problems
from vekna.pacts.circle import Vigil

_HOURLY = 3600
_DAILY = 86400


@pytest.fixture(name="config")
def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


def _project(tmp_path: Path, name: str, toml: str | None = None) -> Path:
    project = tmp_path / name
    project.mkdir()
    if toml is not None:
        (project / ".vekna.toml").write_text(toml, encoding="utf-8")
    return project


def _listed(*projects: Path) -> str:
    return "".join(
        f'[projects.{project.name}]\npath = "{project}"\n' for project in projects
    )


def _prwatch(root: Path, *, ritual: str = "heal.mine", every: int = _HOURLY) -> Vigil:
    return Vigil(
        name="prwatch", project_root=str(root), ritual=ritual, every=every, args={}
    )


class TestVigils:
    @staticmethod
    def test_no_config_is_no_vigils(config: Path, caplog: pytest.LogCaptureFixture):
        assert not config.exists()
        assert ConfigVigils().vigils() == []
        assert not caplog.records

    @staticmethod
    def test_a_top_level_vigil_runs_in_every_project_listed_with_a_checkout(
        config: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        app, api = _project(tmp_path, "app"), _project(tmp_path, "api")
        config.write_text(
            f'[vigil.prwatch]\nevery = {_HOURLY}\nritual = "heal.mine"\n'
            'args = { author = "me", max_prs = 3 }\n'
            + _listed(app, api)
            + '[projects.gone]\npath = "/no/such/checkout"\n',
            encoding="utf-8",
        )

        assert ConfigVigils().vigils() == [
            Vigil(
                name="prwatch",
                project_root=str(root),
                ritual="heal.mine",
                every=_HOURLY,
                args={"author": "me", "max_prs": 3},
            )
            for root in (app, api)
        ]
        assert not caplog.records

    @staticmethod
    def test_a_project_nobody_listed_is_not_read(config: Path, tmp_path: Path):
        _project(tmp_path, "app", '[vigil.prwatch]\nevery = 60\nritual = "heal"\n')
        config.write_text(
            '[vigil.prwatch]\nevery = 60\nritual = "heal"\n', encoding="utf-8"
        )

        assert ConfigVigils().vigils() == []

    @staticmethod
    def test_the_nearest_table_replaces_a_farther_one_of_its_name_whole(
        config: Path, tmp_path: Path
    ):
        app = _project(
            tmp_path, "app", f'[vigil.prwatch]\nevery = {_DAILY}\nritual = "heal.pr"\n'
        )
        api, web = _project(tmp_path, "api"), _project(tmp_path, "web")
        config.write_text(
            f'[vigil.prwatch]\nevery = {_HOURLY}\nritual = "heal.mine"\n'
            "args = { author = 1 }\n"
            + _listed(app, api, web)
            + f'[projects.api.vigil.prwatch]\nevery = {_DAILY}\nritual = "heal.main"\n'
            f'[projects.api.vigil.tidy]\nevery = {_DAILY}\nritual = "tidy"\n',
            encoding="utf-8",
        )

        assert ConfigVigils().vigils() == [
            _prwatch(app, ritual="heal.pr", every=_DAILY),
            _prwatch(api, ritual="heal.main", every=_DAILY),
            Vigil(
                name="tidy", project_root=str(api), ritual="tidy", every=_DAILY, args={}
            ),
            Vigil(
                name="prwatch",
                project_root=str(web),
                ritual="heal.mine",
                every=_HOURLY,
                args={"author": 1},
            ),
        ]

    @staticmethod
    def test_a_table_that_will_not_read_is_said_once_and_passed_over(
        config: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        app = _project(tmp_path, "app", '[vigil.prwatch]\nevery = 0\nritual = "x"\n')
        config.write_text(
            f'[vigil.prwatch]\nevery = {_HOURLY}\nritual = "heal.mine"\n'
            + _listed(app),
            encoding="utf-8",
        )
        book = ConfigVigils()

        assert book.vigils() == [_prwatch(app)]
        assert book.vigils() == [_prwatch(app)]

        [said] = caplog.records
        assert said.levelno == logging.WARNING
        assert said.getMessage().startswith(f"{app / '.vekna.toml'}: ")
        assert said.getMessage().endswith(" — [vigil] ignored")

    @staticmethod
    def test_a_problem_that_comes_back_is_said_again(
        config: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ):
        app = _project(tmp_path, "app")
        broken = '[vigil.prwatch]\nritual = "heal"\n' + _listed(app)
        book = ConfigVigils()

        for toml in (broken, _listed(app), broken):
            config.write_text(toml, encoding="utf-8")
            assert book.vigils() == []

        assert len(caplog.records) == len((broken, broken))


class TestProblems:
    @staticmethod
    @pytest.mark.usefixtures("config")
    def test_a_key_a_vigil_does_not_take_is_named(tmp_path: Path):
        app = _project(
            tmp_path, "app", '[vigil.prwatch]\nevery = 60\nritual = "x"\ncron = "*"\n'
        )

        [said] = vigil_problems(app)

        assert said.startswith(f"{app / '.vekna.toml'}: ")
        assert "cron" in said

    @staticmethod
    @pytest.mark.usefixtures("config")
    def test_a_table_that_reads_has_none(tmp_path: Path):
        app = _project(tmp_path, "app", '[vigil.prwatch]\nevery = 60\nritual = "x"\n')

        assert vigil_problems(app) == []
