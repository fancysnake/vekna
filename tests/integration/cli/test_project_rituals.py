# The repo's own rituals.py, driven through the CLI that reads it. Every other
# test builds a rituals file of its own, so nothing checked the one this project
# ships. Loading it exercises what no unit test can: that the module imports,
# that every annotation resolves, that each `@ritual` declares a model the CLI
# can render flags from, and that every declared exit names a step.
# Casting is out of scope here — most of these rituals call an agent.

import json
import subprocess
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from vekna.lexicon._inits import rituals_list, rituals_show

_ROOT = Path(__file__).resolve().parents[3]
_EXPECTED = ("review", "cover_diff", "merge_ready", "triage", "nap")


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
        for name in _EXPECTED:
            assert f"{name}" in out
        # The flag rendering that broke on 3.11: an optional Annotated component
        # names the type it validates, not `Optional` or `Annotated`.
        # A whole line: `review` is a suffix of `cabinet:review`, which
        # `.vekna.toml` loads beside it under its own namespace.
        lines = out.splitlines()
        assert "review  [--base <str>] [--only <Path>] [--focus <str>]" in lines
        assert any(line.startswith("cabinet:review  ") for line in lines)
        assert "triage  --link <AnyUrl>\n" in out

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


def _strings(value: object) -> Iterator[str]:
    match value:
        case str():
            yield value
        case dict():
            for item in value.values():
                yield from _strings(item)
        case list():
            for item in value:
                yield from _strings(item)


# `.vekna.toml` hands other tools commands to run, and nothing resolves them
# before a cast does. Keyed off the `mise run ` shape, not any one tool's keys,
# so a block added later is checked without touching this test.
class TestVeknaToml:
    @staticmethod
    def test_every_mise_task_it_names_exists(monkeypatch):
        # mise keeps its trust list under `XDG_STATE_HOME`, which the suite
        # moves to a fresh directory, so the repo's `mise.toml` reads untrusted.
        monkeypatch.setenv("MISE_TRUSTED_CONFIG_PATHS", str(_ROOT))
        config = tomllib.loads((_ROOT / ".vekna.toml").read_text())
        listed = subprocess.run(
            ["mise", "tasks", "--json", "--hidden"],
            cwd=_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        named = {
            command.split()[2]
            for command in _strings(config)
            if command.startswith("mise run ")
        }
        tasks = {task["name"] for task in json.loads(listed.stdout)}
        assert named
        assert named - tasks == set()
