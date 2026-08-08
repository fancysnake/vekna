# The site's CLI page against the CLI. Documentation drifts when a command is
# renamed and the page that names it is in another directory — so this runs
# from `ci.yml` when the Python moves and from `site.yml` when the page does.
# Either side can be the one that drifts.

import re
from pathlib import Path

import click

from vekna.inits.cli import init_command

_REFERENCE = Path(__file__).resolve().parents[3] / "docs" / "cli.md"
# Headings and bash fences, and nothing else on the page. "vekna reads
# `.vekna.toml`" is English; a pattern loose enough to catch it would make the
# page's wording this test's business.
_HEADING = re.compile(r"^#+ `(vekna.*?)`", re.MULTILINE)
_FENCE = re.compile(r"^```bash$(.*?)^```$", re.DOTALL | re.MULTILINE)


def _paths(group: click.Group, prefix: str = "vekna") -> set[str]:
    found: set[str] = set()
    for name, command in group.commands.items():
        found.add(path := f"{prefix} {name}")
        if isinstance(command, click.Group):
            found |= _paths(command, path)
    return found


def _invocations(text: str) -> list[list[str]]:
    lines = _HEADING.findall(text)
    for fence in _FENCE.findall(text):
        lines += [line for line in fence.splitlines() if line.startswith("vekna")]
    return [line.split() for line in lines]


# Where the command path stops is a question only the command tree can answer:
# `vekna cast fix_tests` names a ritual and `vekna rituals delete` names
# nothing, and the tokens look alike. A group is asked what it has; anything
# that is not a group has arguments from here on.
def _walk(tokens: list[str], root: click.Group) -> tuple[str, bool]:
    command: click.Command = root
    path = tokens[0]
    for token in tokens[1:]:
        if token.startswith("-") or not isinstance(command, click.Group):
            break
        if (found := command.commands.get(token)) is None:
            return f"{path} {token}", False
        command, path = found, f"{path} {token}"
    return path, True


def _documented(text: str) -> tuple[set[str], set[str]]:
    walked = [_walk(tokens, init_command()) for tokens in _invocations(text)]
    return (
        {path for path, known in walked if known},
        {path for path, known in walked if not known},
    )


class TestCliReference:
    @staticmethod
    def test_every_command_is_documented():
        documented, _ = _documented(_REFERENCE.read_text())

        undocumented = _paths(init_command()) - documented

        assert not undocumented

    @staticmethod
    def test_no_command_is_documented_that_does_not_exist():
        _, invented = _documented(_REFERENCE.read_text())

        assert not invented

    # The one the old check could not see: it compared the first token against
    # the top-level names, so a subcommand nobody ever wrote passed as long as
    # its parent existed.
    @staticmethod
    def test_a_subcommand_that_does_not_exist_is_caught():
        _, invented = _documented("```bash\nvekna rituals delete\n```\n")

        assert invented == {"vekna rituals delete"}
