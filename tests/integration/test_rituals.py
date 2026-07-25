import textwrap

import pytest

from vekna.lexicon.entry import rituals_list, rituals_show

_USAGE_EXIT = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(start: int, label: str = "run") -> Transition:
        return goto(tick, Tick(left=start))


    @ritual("ping")
    async def ping() -> Transition:
        return done("pong")
    """)

_BROKEN = "import a_module_that_does_not_exist\n"


@pytest.fixture
def _home(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


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
