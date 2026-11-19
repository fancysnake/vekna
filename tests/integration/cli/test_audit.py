import subprocess
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command

_UNCHECKED = "[defaults] were not fully checked: the rituals did not all load"
_TOME = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Done, ritual


    class Echo(BaseModel):
        said: str


    @ritual("echo")
    async def echo(components: Echo) -> Done[Echo]:
        return Done(components)
    """)


@pytest.fixture(name="user")
def _user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


@pytest.fixture(name="repo")
def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "tomes" / "vekna_test_audit_tome").mkdir(parents=True)
    (tmp_path / "tomes" / "vekna_test_audit_tome" / "__init__.py").write_text(_TOME)
    monkeypatch.syspath_prepend(str(tmp_path / "tomes"))
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    monkeypatch.chdir(repo)
    return repo


def _audit() -> tuple[int, str]:
    result = CliRunner().invoke(init_command(), ["audit"])
    return result.exit_code, result.output


class TestAudit:
    @staticmethod
    def test_each_setting_names_its_layer_and_what_sets_nothing_is_listed(
        user: Path, repo: Path
    ):
        user.write_text(
            "[circle]\nprocesses = 2\ncoding = 1\n"
            f'[projects.mine]\npath = "{repo}"\n'
            "[projects.mine.circle]\nprocesses = 2\nworktrees = 9\n"
            '[projects.gone]\npath = "/no/such/checkout"\n'
            f'[projects.bare]\npath = "{repo.parent}"\n',
            encoding="utf-8",
        )
        project = repo / ".vekna.toml"
        project.write_text(
            '[circle]\nworktrees = 3\ncoding = 5\n[cabinet]\nremote = "https"\n',
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            f"  2  {user}: [projects.mine]\n"
            f"  3  {user}\n"
            "\n"
            "[circle]\n"
            "  worktrees = 3  ← 1 (over 2: 9)\n"
            "  coding = 1  ← 3\n"
            "  processes = 2  ← 2\n"
            "[cabinet]\n"
            '  remote = "https"  ← 1\n'
            "\n"
            "pointless:\n"
            f"  {user}: [projects.gone] path = '/no/such/checkout' does not exist\n"
            f"  {user}: [projects.mine.circle] worktrees = 9 is overridden by"
            f" {project}: [circle]\n"
            f"  {project}: [circle] coding is ignored: only {user}'s own [circle]"
            " sets it\n"
            f"  {user}: [projects.mine.circle] processes = 2 repeats {user}: [circle]\n"
            f"  {project}: [cabinet]: vekna reads no [cabinet] and no tome named"
            " 'cabinet' is in [rituals] modules — stale, unless another tool reads"
            " it\n"
        )
        assert code == 0

    @staticmethod
    @pytest.mark.usefixtures("repo")
    def test_a_relative_project_path_is_refused_not_called_a_missing_checkout(
        user: Path,
    ):
        user.write_text('[projects.near]\npath = "no/such"\n', encoding="utf-8")

        code, said = _audit()

        assert said == (
            f"layers, nearest first:\n  1  {user}\n\nerrors:\n"
            f"  {user}: [projects.near] path = 'no/such' is not absolute\n"
            f"  {_UNCHECKED}\n"
        )
        assert code == 1

    @staticmethod
    def test_every_broken_table_is_named_and_the_audit_fails(user: Path, repo: Path):
        user.write_text(
            "[window]\nhistory_after = 3\ntheme = 1\n[projects.bad]\nkey = 1\n",
            encoding="utf-8",
        )
        project = repo / ".vekna.toml"
        project.write_text(
            "defaults = 3\n[circle]\nspeed = 1\n[rituals]\nmodule = []\n",
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            f"  2  {user}\n"
            "\n"
            "[circle]\n"
            "  speed = 1  ← 1\n"
            "[window]\n"
            "  history_after = 3  ← 2\n"
            "  theme = 1  ← 2\n"
            "\n"
            "errors:\n"
            f"  {user}: [projects.bad] needs a path, the project's checkout\n"
            f"  {project}: circle.speed: Extra inputs are not permitted"
            " — [circle] ignored\n"
            f"  {user}: window.theme: Extra inputs are not permitted"
            " — [window] ignored\n"
            f"  {project}: rituals.module: Extra inputs are not permitted;"
            " defaults: Input should be a valid dictionary\n"
            f"  {_UNCHECKED}\n"
        )
        assert code == 1

    @staticmethod
    def test_defaults_are_checked_against_the_rituals_loaded_here(
        user: Path, repo: Path
    ):
        user.write_text(
            '[rituals]\nmodules = { t = "vekna_test_audit_tome" }\n'
            "[defaults.elsewhere]\nkey = 1\n",
            encoding="utf-8",
        )
        project = repo / ".vekna.toml"
        project.write_text(
            '[defaults."t:echo"]\nsaid = "hi"\nloud = true\n'
            "[defaults.ghost]\nkey = 1\n",
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            f"  2  {user}\n"
            "\n"
            "[rituals]\n"
            "  modules t = vekna_test_audit_tome  ← 2\n"
            "[defaults.t:echo]\n"
            '  said = "hi"  ← 1\n'
            "  loud = true  ← 1\n"
            "[defaults.ghost] (no such ritual here)\n"
            "  key = 1  ← 1\n"
            "[defaults.elsewhere] (no such ritual here)\n"
            "  key = 1  ← 2\n"
            "\n"
            "errors:\n"
            f"  {project}: [defaults.t:echo] sets 'loud', which t:echo does not take\n"
            "\n"
            "pointless:\n"
            f"  {project}: [defaults.ghost]: no ritual named 'ghost' is loaded here\n"
        )
        assert code == 1

    @staticmethod
    def test_a_tome_that_does_not_import_leaves_defaults_unchecked(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        del user
        project = repo / ".vekna.toml"
        project.write_text(
            '[rituals]\nmodules = ["vekna_no_such_tome"]\n[defaults.ghost]\nkey = 1\n',
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            "\n"
            "[rituals]\n"
            "  modules vekna_no_such_tome = vekna_no_such_tome  ← 1\n"
            "[defaults.ghost]\n"
            "  key = 1  ← 1\n"
            "\n"
            "errors:\n"
            "  vekna_no_such_tome failed to import: ModuleNotFoundError:"
            " No module named 'vekna_no_such_tome'\n"
            f"  {_UNCHECKED}\n"
        )
        assert code == 1
        assert not capsys.readouterr().err

    @staticmethod
    def test_a_ritual_source_that_does_not_import_is_an_error(user: Path, repo: Path):
        source = repo / "rituals.py"
        source.write_text("import vekna_no_such_module\n")
        project = repo / ".vekna.toml"
        project.write_text(
            '[rituals]\nfiles = ["rituals.py"]\n[circle]\ncoding = 5\n',
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            "\n"
            "[rituals]\n"
            f"  files {source}  ← 1\n"
            "\n"
            "errors:\n"
            f"  {source} failed to import: ModuleNotFoundError:"
            " No module named 'vekna_no_such_module'\n"
            f"  {_UNCHECKED}\n"
            "\n"
            "pointless:\n"
            f"  {project}: [circle] coding is ignored: only {user}'s own [circle]"
            " sets it\n"
        )
        assert code == 1

    @staticmethod
    def test_a_name_collision_keeps_the_skipped_tome_in_the_report(
        user: Path, repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        del user
        (repo / "one.py").write_text(_TOME, encoding="utf-8")
        (repo / "two.py").write_text(_TOME, encoding="utf-8")
        project = repo / ".vekna.toml"
        project.write_text(
            '[rituals]\nfiles = ["one.py", "two.py"]\n'
            'modules = ["vekna_no_such_tome"]\n',
            encoding="utf-8",
        )

        code, said = _audit()

        assert said == (
            "layers, nearest first:\n"
            f"  1  {project}\n"
            "\n"
            "[rituals]\n"
            "  modules vekna_no_such_tome = vekna_no_such_tome  ← 1\n"
            f"  files {repo / 'one.py'}  ← 1\n"
            f"  files {repo / 'two.py'}  ← 1\n"
            "\n"
            "errors:\n"
            "  warning: vekna_no_such_tome failed to import: ModuleNotFoundError:"
            " No module named 'vekna_no_such_tome' — its rituals are skipped\n"
            "  name collisions:\n"
            f"    ritual 'echo' — declared in both {repo / 'one.py'}"
            f" and {repo / 'two.py'}\n"
            f"  {_UNCHECKED}\n"
        )
        assert code == 1
        assert not capsys.readouterr().err

    @staticmethod
    def test_no_config_at_all_is_said_and_is_no_error(user: Path, repo: Path):
        del repo

        code, said = _audit()

        assert said == (
            "no config was read: a project's is .vekna.toml,"
            f" the user's is {user}\n\nno errors, nothing pointless\n"
        )
        assert code == 0
