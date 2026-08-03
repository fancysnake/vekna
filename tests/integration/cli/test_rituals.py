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
        note: str | None = None


    class Pong(BaseModel):
        said: str


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
        return done(Pong(said="pong"))
    """)

_BROKEN = "import a_module_that_does_not_exist\n"

# The same two rituals as `_RITUALS`, split the way the feature exists to allow:
# an empty `__init__.py`, models in one module, prose in another, and every step
# in a third that reaches both by relative import.
_COMPONENTS = textwrap.dedent("""
    from pydantic import BaseModel


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int


    class Pong(BaseModel):
        said: str
    """)

_PROMPTS = 'GREETING = "pong"\n'

_STEPS = textwrap.dedent("""
    from vekna.lexicon import NoComponents, Transition, done, goto, ritual, step

    from .components import Countdown, Pong, Tick
    from .prompts import GREETING


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
        return done(Pong(said=GREETING))
    """)

# A level down, reaching two levels up for what it needs.
_DEEP_STEPS = textwrap.dedent("""
    from vekna.lexicon import Transition, done, goto, ritual, step

    from ..components import Countdown, Tick
    from ..prompts import GREETING


    @step
    async def deeper(state: Tick) -> Transition:
        return done(Tick(left=state.left + len(GREETING)))


    @ritual("dig")
    async def dig(components: Countdown) -> Transition:
        return goto(deeper, Tick(left=components.start))
    """)

_PACKAGE = {
    "__init__.py": "",
    "components.py": _COMPONENTS,
    "prompts.py": _PROMPTS,
    "steps.py": _STEPS,
}


def _write(root, files):
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


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
        assert "countdown  --start <int> [--label <str>] [--note <str>]\n" in out
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
        assert "  --note <str>  (optional)\n" in out
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
class TestRitualPackages:
    @staticmethod
    def test_a_package_is_found_and_lists_every_ritual(tmp_path, monkeypatch, capsys):
        _write(tmp_path / "rituals", _PACKAGE)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "countdown  --start <int>\n" in out
        assert "ping\n" in out

    @staticmethod
    def test_a_package_is_found_by_walking_up(tmp_path, monkeypatch, capsys):
        _write(tmp_path / "rituals", _PACKAGE)
        (deep := tmp_path / "src" / "nested").mkdir(parents=True)
        monkeypatch.chdir(deep)

        exit_code = rituals_list()

        assert exit_code == 0
        assert "ping\n" in capsys.readouterr().out

    # The whole point of the sweep: `__init__.py` names neither step, and the
    # graph is drawn to its end rather than stopping at the first one.
    @staticmethod
    def test_show_draws_a_graph_the_init_never_mentions(tmp_path, monkeypatch, capsys):
        _write(tmp_path / "rituals", _PACKAGE)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("countdown")

        out = capsys.readouterr().out
        assert exit_code == 0
        assert not (tmp_path / "rituals" / "__init__.py").read_text()
        assert "  (start) → tick\n" in out
        assert "  tick → tick, (done)\n" in out

    @staticmethod
    def test_an_init_may_import_from_a_sibling(tmp_path, monkeypatch, capsys):
        _write(
            tmp_path / "rituals",
            {**_PACKAGE, "__init__.py": "from .prompts import GREETING\n"},
        )
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        assert exit_code == 0
        assert "ping\n" in capsys.readouterr().out

    @staticmethod
    def test_a_nested_subpackage_is_swept(tmp_path, monkeypatch, capsys):
        _write(
            tmp_path / "rituals",
            {**_PACKAGE, "deep/__init__.py": "", "deep/steps.py": _DEEP_STEPS},
        )
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("dig")

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "  (start) → deeper\n" in out
        assert "  deeper → (done)\n" in out

    # `pkgutil.iter_modules` yields a directory holding no `__init__` as nothing
    # at all, so a namespace-package level would go unswept in silence.
    @staticmethod
    def test_a_directory_without_an_init_is_not_swept(tmp_path, monkeypatch, capsys):
        _write(tmp_path / "rituals", {**_PACKAGE, "loose/steps.py": _DEEP_STEPS})
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "ping\n" in out
        assert "dig" not in out

    @staticmethod
    def test_a_directory_without_an_init_is_not_a_source(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        _write(tmp_path / "nested" / "rituals", {"steps.py": _STEPS})
        monkeypatch.chdir(tmp_path / "nested")

        exit_code = rituals_list()

        assert exit_code == 0
        assert "ping\n" in capsys.readouterr().out

    @staticmethod
    def test_a_file_beside_a_package_is_an_error(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        _write(tmp_path / "rituals", _PACKAGE)
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        err = capsys.readouterr().err
        assert exit_code == _USAGE_EXIT
        assert str(tmp_path / "rituals.py") in err
        assert str(tmp_path / "rituals") in err

    # And the walk stops there rather than reaching past the ambiguity to a
    # parent that has a source of its own.
    @staticmethod
    def test_the_walk_stops_at_the_ambiguity(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        (below := tmp_path / "below").mkdir()
        (below / "rituals.py").write_text(_RITUALS)
        _write(below / "rituals", _PACKAGE)
        monkeypatch.chdir(below)

        exit_code = rituals_list()

        assert exit_code == _USAGE_EXIT
        assert str(below / "rituals.py") in capsys.readouterr().err

    @staticmethod
    def test_a_submodule_that_cannot_be_imported_is_a_usage_error(
        tmp_path, monkeypatch, capsys
    ):
        _write(tmp_path / "rituals", {**_PACKAGE, "broken.py": _BROKEN})
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        assert exit_code == _USAGE_EXIT
        assert "a_module_that_does_not_exist" in capsys.readouterr().err


@pytest.mark.usefixtures("_home")
class TestRitualSources:
    @staticmethod
    def test_a_malformed_config_stops_the_command(tmp_path, monkeypatch, capsys):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nmodule = ["pkg.rites"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        err = capsys.readouterr().err
        assert exit_code == _USAGE_EXIT
        assert ".vekna.toml" in err
        assert "module" in err

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

    # A console script's sys.path[0] is the venv's bin, so the project being
    # cast is on the path of nothing until the loader puts it there.
    @staticmethod
    def test_a_configured_package_resolves_without_pythonpath(
        tmp_path, monkeypatch, capsys
    ):
        _write(tmp_path / "mylib", _PACKAGE)
        (tmp_path / ".vekna.toml").write_text('[rituals]\nmodules = ["mylib"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "ping\n" in out

    @staticmethod
    def test_a_configured_package_is_swept_to_the_bottom(tmp_path, monkeypatch, capsys):
        _write(
            tmp_path / "mylib",
            {**_PACKAGE, "deep/__init__.py": "", "deep/steps.py": _DEEP_STEPS},
        )
        (tmp_path / ".vekna.toml").write_text('[rituals]\nmodules = ["mylib"]\n')
        monkeypatch.chdir(tmp_path)

        exit_code = rituals_show("dig")

        out = capsys.readouterr().out
        assert exit_code == 0
        assert "  deeper → (done)\n" in out

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
