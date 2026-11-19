# The repo's own rituals.py, driven through the CLI that reads it. Every other
# test builds a rituals file of its own, so nothing checked the one this project
# ships. Loading it exercises what no unit test can: that the module imports,
# that every annotation resolves, that each `@ritual` declares a model the CLI
# can render flags from, and that every declared exit names a step.
# Casting is out of scope here — most of these rituals call an agent.

from pathlib import Path

import pytest

from vekna.lexicon._inits import rituals_list, rituals_show

_ROOT = Path(__file__).resolve().parents[3]
_EXPECTED = ("ci_watch", "cover_diff", "merge_ready", "nap", "pr_fix", "sweep", "tree")


def _stand_at_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # HOME too: _config_files reads ~/.config/vekna/config.toml, and a real one
    # would add rituals this test did not put there.
    monkeypatch.setenv("HOME", str(_ROOT / "does-not-exist"))
    monkeypatch.chdir(_ROOT)


# A test's step scope keeps only the steps registered before it opened, and the
# project's modules import once per process: imported inside the first test,
# their steps are forgotten with it and never declared again. Module scope sets
# up before any test's scope opens, as a suite importing them at collection does.
@pytest.fixture(scope="module", autouse=True)
def _rituals_imported() -> None:
    with pytest.MonkeyPatch.context() as monkeypatch:
        _stand_at_root(monkeypatch)
        rituals_list()


@pytest.fixture
def _at_root(monkeypatch) -> None:
    _stand_at_root(monkeypatch)


@pytest.mark.usefixtures("_at_root")
class TestProjectRituals:
    @staticmethod
    def test_every_ritual_loads_and_lists_its_flags(capsys):
        exit_code = rituals_list()

        out = capsys.readouterr().out
        assert not exit_code
        lines = out.splitlines()
        for name in _EXPECTED:
            assert any(line.startswith(f"{name}  ") for line in lines)

    @staticmethod
    @pytest.mark.parametrize("name", _EXPECTED)
    def test_each_step_graph_resolves(name, capsys):
        exit_code = rituals_show(name)

        out = capsys.readouterr().out
        assert not exit_code
        assert out.startswith(f"{name}\n")
        # `?` is what `show` prints for a node with no exits at all, and
        # `(start)` proves the entrypoint's own exits were read.
        assert "?" not in out
        assert "(start) → " in out

    @staticmethod
    def test_the_concurrent_quality_gates_step_is_reachable(capsys):
        rituals_show("merge_ready")

        out = capsys.readouterr().out
        assert "  (start) → quality_gates\n" in out
        assert "  quality_gates → repair, (done)\n" in out
        assert "  repair → quality_gates\n" in out
