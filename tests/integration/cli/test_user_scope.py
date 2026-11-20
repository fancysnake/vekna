import subprocess
import textwrap
from pathlib import Path

import pytest

from vekna.lexicon import ConfigTable, RitualDefinitionError, config_table
from vekna.lexicon._inits import main, rituals_show

_USAGE_EXIT = 2

_TOME = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Done, ritual


    class Echo(BaseModel):
        said: str


    @ritual("echo")
    async def echo(components: Echo) -> Done[Echo]:
        return Done(components)


    class Strict(BaseModel):
        level: int


    @ritual("strict")
    async def strict(components: Strict) -> Done[Strict]:
        return Done(components)
    """)


@pytest.fixture(name="user")
def _user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


# A repository with no `.vekna.toml` and no rituals of its own, beside a tome
# its interpreter can import.
@pytest.fixture(name="repo")
def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tomes" / "vekna_test_user_tome").mkdir(parents=True)
    (tmp_path / "tomes" / "vekna_test_user_tome" / "__init__.py").write_text(_TOME)
    monkeypatch.syspath_prepend(str(tmp_path / "tomes"))
    repo = tmp_path / "repo"
    (repo / "deep").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo / "deep")
    return repo


class TestUserScope:
    @staticmethod
    def test_a_project_the_user_names_casts_with_no_config_of_its_own(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        user.write_text(
            '[rituals]\nmodules = { t = "vekna_test_user_tome" }\n'
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.defaults."t:echo"]\nsaid = "hello"\n',
            encoding="utf-8",
        )

        assert main(["echo"]) == 0
        assert not list(repo.glob(".vekna.toml"))
        capsys.readouterr()
        assert rituals_show("echo") == 0
        shown = capsys.readouterr().out
        assert f"--said <str>  = hello ({user}: [projects.mine])" in shown

    @staticmethod
    def test_a_tome_the_user_names_for_one_project_is_not_cast_elsewhere(
        user: Path,
        repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        user.write_text(
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.rituals]\nmodules = { t = "vekna_test_user_tome" }\n',
            encoding="utf-8",
        )

        assert main(["echo", "--said", "here"]) == 0
        monkeypatch.chdir(tmp_path)
        capsys.readouterr()
        assert main(["echo", "--said", "there"]) == _USAGE_EXIT
        assert "echo" in capsys.readouterr().err

    @staticmethod
    def test_the_project_s_file_wins_over_the_user_s_table_for_the_project(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        (repo / ".vekna.toml").write_text(
            '[rituals]\nmodules = { t = "vekna_test_user_tome" }\n'
            '[defaults."t:strict"]\nlevel = 1\n',
            encoding="utf-8",
        )
        user.write_text(
            '[defaults."t:strict"]\nlevel = 3\n'
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.defaults."t:strict"]\nlevel = 7\n',
            encoding="utf-8",
        )

        assert rituals_show("strict") == 0
        shown = capsys.readouterr().out
        assert f"--level <int>  = 1 ({repo / '.vekna.toml'})" in shown

    # What a ritual needs is checked when that ritual is cast: a setting one
    # ritual refuses is not the business of a cast of another.
    @staticmethod
    def test_a_default_one_ritual_refuses_does_not_stop_a_cast_of_another(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        user.write_text(
            '[rituals]\nmodules = { t = "vekna_test_user_tome" }\n'
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.defaults."t:strict"]\nlevel = "high"\n',
            encoding="utf-8",
        )

        assert main(["echo", "--said", "fine"]) == 0
        capsys.readouterr()
        assert main(["strict"]) == _USAGE_EXIT
        assert "[projects.mine.defaults.t:strict]" in capsys.readouterr().err

    @staticmethod
    def test_files_in_the_user_s_table_for_a_project_are_refused(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        user.write_text(
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.rituals]\nfiles = ["rituals.py"]\n',
            encoding="utf-8",
        )

        assert main(["echo"]) == _USAGE_EXIT
        assert (
            capsys.readouterr()
            .err.strip()
            .endswith(
                f"{user}: [projects.mine.rituals] takes no files"
                " — rituals a project defines are named in its own .vekna.toml"
            )
        )

    @staticmethod
    def test_a_misspelt_table_inside_a_project_table_is_named(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        user.write_text(
            f'[projects.mine]\npath = "{repo}"\n[projects.mine.ritual]\n',
            encoding="utf-8",
        )

        assert main(["echo"]) == _USAGE_EXIT
        assert (
            f"{user}: [projects.mine]: vekna reads no [ritual] table"
            " — did you mean [rituals]?"
        ) in capsys.readouterr().err

    @staticmethod
    def test_a_project_table_with_no_path_stops_the_cast(
        user: Path, capsys: pytest.CaptureFixture[str]
    ):
        user.write_text("[projects.mine]\n", encoding="utf-8")

        assert main(["echo"]) == _USAGE_EXIT
        assert f"{user}: [projects.mine] needs a path" in capsys.readouterr().err


class TestConfigTable:
    @staticmethod
    def test_a_tome_s_table_is_merged_nearest_first(user: Path, repo: Path):
        (repo / ".vekna.toml").write_text(
            '[cabinet]\ngate = "project"\ncoverage = "project"\n', encoding="utf-8"
        )
        user.write_text(
            '[cabinet]\ngate = "user"\nremote = "https-origin"\n'
            '[cabinet.agent]\nmay_not_run = ["slow"]\n'
            f'[projects.mine]\npath = "{repo}"\n'
            '[projects.mine.cabinet]\ngate = "mine"\n'
            '[projects.mine.cabinet.agent]\neffort = "high"\n',
            encoding="utf-8",
        )

        assert config_table("cabinet") == ConfigTable(
            {
                "gate": "project",
                "coverage": "project",
                "remote": "https-origin",
                "agent": {"may_not_run": ["slow"], "effort": "high"},
            },
            (
                f"{repo / '.vekna.toml'}: [cabinet]",
                f"{user}: [projects.mine.cabinet]",
                f"{user}: [cabinet]",
            ),
        )

    @staticmethod
    def test_a_table_nobody_sets_is_empty(user: Path, tmp_path: Path):
        user.write_text("[circle]\nprocesses = 2\n", encoding="utf-8")

        assert config_table("cabinet", tmp_path) == ConfigTable({}, ())

    @staticmethod
    def test_a_config_that_will_not_read_is_refused_by_name(user: Path, tmp_path: Path):
        user.write_text("[cabinet\n", encoding="utf-8")

        with pytest.raises(RitualDefinitionError, match=str(user)):
            config_table("cabinet", tmp_path)
