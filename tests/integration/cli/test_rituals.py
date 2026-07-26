import sys
import textwrap

import pytest

from vekna.lexicon._inits import rituals_list, rituals_show

_USAGE_EXIT = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int
        label: str = "run"


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(components: Countdown) -> Transition:
        return goto(tick, Tick(left=components.start))


    @ritual("ping")
    async def ping(_: NoComponents) -> Transition:
        return done("pong")
    """)

_BROKEN = "import a_module_that_does_not_exist\n"


@pytest.fixture
def _home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


_SHARED = "shared_rituals"


# Importable by name and gone again afterwards: load_rituals_module leaves the
# module in sys.modules, where it would otherwise leak into later tests.
@pytest.fixture
def _shared_module(tmp_path, monkeypatch):
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / f"{_SHARED}.py").write_text(_RITUALS)
    monkeypatch.syspath_prepend(str(lib))
    yield
    sys.modules.pop(_SHARED, None)


@pytest.mark.usefixtures("_home")
class TestRitualsList:
    @staticmethod
    def test_lists_every_ritual_with_its_options(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "countdown  --start <int> [--label <str>]\n" in out
        assert "ping\n" in out

    @staticmethod
    def test_reports_when_no_rituals_are_found(tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        assert exit_code == 0
        assert "no rituals found" in capsys.readouterr().out


@pytest.mark.usefixtures("_home")
class TestRitualsShow:
    @staticmethod
    def test_shows_components_and_step_graph(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("countdown")

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "countdown\nmax steps: " in out
        assert "  --start <int>\n" in out
        assert "  --label <str>  (optional)\n" in out
        assert "  (start) → tick\n" in out
        assert "  tick → tick, (done)\n" in out

    @staticmethod
    def test_shows_none_for_a_ritual_without_components(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("ping")

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "components:\n  (none)\n" in out
        assert "  (start) → (done)\n" in out

    @staticmethod
    def test_unknown_ritual_is_a_usage_error(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("nope")

        assert exit_code == _USAGE_EXIT
        assert "no ritual named 'nope'" in capsys.readouterr().err


@pytest.mark.usefixtures("_home")
class TestRitualSources:
    @staticmethod
    def test_config_may_name_the_discovered_rituals_file(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nfiles = ["rituals.py"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.count("ping\n") == 1

    @staticmethod
    def test_a_file_reached_by_two_spellings_loads_once(tmp_path, monkeypatch, capsys):
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "rituals.py").write_text(_RITUALS)
        (nested / ".vekna.toml").write_text(
            '[rituals]\nfiles = ["../nested/rituals.py"]\n'
        )
        monkeypatch.chdir(nested)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.count("ping\n") == 1

    @staticmethod
    @pytest.mark.usefixtures("_shared_module")
    def test_one_module_named_by_two_configs_loads_once(tmp_path, monkeypatch, capsys):
        config = tmp_path / "home" / ".config" / "vekna"
        config.mkdir(parents=True)
        (config / "config.toml").write_text(f'[rituals]\nmodules = ["{_SHARED}"]\n')
        project = tmp_path / "project"
        project.mkdir()
        (project / ".vekna.toml").write_text(f'[rituals]\nmodules = ["{_SHARED}"]\n')
        monkeypatch.chdir(project)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert out.count("ping\n") == 1

    @staticmethod
    def test_two_different_files_claiming_one_name_still_collide(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        (tmp_path / "extra.py").write_text(_RITUALS)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nfiles = ["extra.py"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        err = capsys.readouterr().err
        assert exit_code == _USAGE_EXIT
        assert "declared in both" in err
        assert "extra.py" in err


@pytest.mark.usefixtures("_home")
class TestRitualsUsage:
    @staticmethod
    def test_rituals_that_cannot_be_loaded_are_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_BROKEN)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        assert exit_code == _USAGE_EXIT
        assert "a_module_that_does_not_exist" in capsys.readouterr().err

    @staticmethod
    def test_showing_a_ritual_that_cannot_be_loaded_is_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "rituals.py").write_text(_BROKEN)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("countdown")

        assert exit_code == _USAGE_EXIT
        assert "a_module_that_does_not_exist" in capsys.readouterr().err
