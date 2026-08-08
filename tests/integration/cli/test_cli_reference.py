# The site's CLI page against the CLI. Documentation drifts when a command is
# renamed and the page that names it is in another directory — so the check
# lives with the tests that run on every Python change, which is the change
# that causes the drift.

import re
from pathlib import Path

import click

from vekna.inits.cli import init_command

_REFERENCE = Path(__file__).resolve().parents[3] / "docs" / "cli.md"
# `vekna cast`, `vekna rituals list` — the invocations the page shows, minus
# anything that follows a flag or a ritual name.
_INVOCATION = re.compile(r"\bvekna\s+([a-z][a-z-]*)")


def _paths(group: click.Group, prefix: str = "vekna") -> set[str]:
    found: set[str] = set()
    for name, command in group.commands.items():
        found.add(path := f"{prefix} {name}")
        if isinstance(command, click.Group):
            found |= _paths(command, path)
    return found


class TestCliReference:
    @staticmethod
    def test_every_command_is_documented():
        text = _REFERENCE.read_text()

        undocumented = {path for path in _paths(init_command()) if path not in text}

        assert not undocumented

    @staticmethod
    def test_no_command_is_documented_that_does_not_exist():
        top_level = set(init_command().commands)

        invented = {
            name
            for name in _INVOCATION.findall(_REFERENCE.read_text())
            if name not in top_level
        }

        assert not invented
