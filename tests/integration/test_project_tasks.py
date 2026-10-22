# `.vekna.toml` and the project's rituals hand mise commands to run, and nothing
# resolves them before a cast does. Keyed off the `mise run ` shape, not any
# one tool's keys, so a block or ritual added later is checked without touching
# this test. A command built by an f-string is not a constant and goes unchecked.

import ast
import json
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

from vekna.wire import TomlValue, read_toml

_ROOT = Path(__file__).resolve().parents[2]
_MISE_RUN = re.compile(r"mise run ([^\s`]+)")


def _strings(value: TomlValue) -> Iterator[str]:
    match value:
        case str():
            yield value
        case dict():
            for item in value.values():
                yield from _strings(item)
        case list():
            for item in value:
                yield from _strings(item)


def _ritual_strings() -> Iterator[str]:
    for path in (_ROOT / "src" / "rituals").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield node.value


class TestProjectTasks:
    @staticmethod
    def test_every_mise_task_named_exists(monkeypatch):
        # mise keeps its trust list under `XDG_STATE_HOME`, which the suite
        # moves to a fresh directory, so the repo's `mise.toml` reads untrusted.
        monkeypatch.setenv("MISE_TRUSTED_CONFIG_PATHS", str(_ROOT))
        commands = [*_strings(read_toml(_ROOT / ".vekna.toml")), *_ritual_strings()]
        # The timeout because `mise.toml` includes tasks over `git::https`.
        listed = subprocess.run(
            ["mise", "tasks", "--json", "--hidden"],
            cwd=_ROOT,
            check=True,
            stdout=subprocess.PIPE,
            text=True,
            timeout=60,
        )

        named = {
            match[1] for command in commands for match in _MISE_RUN.finditer(command)
        }
        tasks = {task["name"] for task in json.loads(listed.stdout)}
        assert named
        assert named - tasks == set()
