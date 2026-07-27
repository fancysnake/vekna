"""The repo's own rituals.py, driven through the CLI that reads it.

Every other test builds a rituals file of its own, so nothing checked the one
this project ships. Loading it exercises what no unit test can: that the module
imports, that every annotation resolves, that each `@ritual` declares a model
the CLI can render flags from, and that every `goto` names a step the graph can
find. Casting is out of scope here — three of the four rituals call an agent.
"""

from pathlib import Path

import pytest

from vekna.lexicon._inits import rituals_list, rituals_show

_ROOT = Path(__file__).resolve().parents[3]
_EXPECTED = ("cover_diff", "merge_ready", "review", "triage")


@pytest.fixture
def _at_root(monkeypatch) -> None:
    # HOME too: _config_files reads ~/.config/vekna/config.toml, and a real one
    # would add rituals this test did not put there.
    monkeypatch.setenv("HOME", str(_ROOT / "does-not-exist"))
    monkeypatch.chdir(_ROOT)


@pytest.mark.usefixtures("_at_root")
class TestProjectRituals:
    @staticmethod
    def test_every_ritual_loads_and_lists_its_flags(capsys):
        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert not exit_code
        for name in _EXPECTED:
            assert f"{name}" in out
        # The flag rendering that broke on 3.11: an optional Annotated component
        # names the type it validates, not `Optional` or `Annotated`.
        assert "review  [--base <str>] [--only <Path>] [--focus <str>]\n" in out
        assert "triage  --link <AnyUrl>\n" in out

    @staticmethod
    @pytest.mark.parametrize("name", _EXPECTED)
    def test_each_step_graph_resolves(name, capsys):
        exit_code = rituals_show(name)

        out = capsys.readouterr().out
        assert not exit_code
        assert out.startswith(f"{name}\n")
        # `?` is what step_graph prints for a goto whose target it cannot find,
        # and `(start)` proves the entrypoint's own transition was read.
        assert "?" not in out
        assert "(start) → " in out

    @staticmethod
    def test_the_concurrent_gates_step_is_reachable(capsys):
        rituals_show("merge_ready")

        out = capsys.readouterr().out
        assert "  (start) → gates\n" in out
        assert "  gates → repair, (done)\n" in out
        assert "  repair → gates\n" in out
