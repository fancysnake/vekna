# The binary's own door: `vekna.inits.cli` names the cast runtime as a string
# so the daemon never imports the lexicon, and a rename on either side of that
# string is invisible to the type checker. Only running the commands catches it.

import textwrap

import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command

_USAGE_EXIT = 2

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(components: Countdown) -> Transition:
        return goto(tick, Tick(left=components.start))
    """)


@pytest.fixture
def _project(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "rituals.py").write_text(_RITUALS)
    monkeypatch.chdir(tmp_path)


@pytest.mark.usefixtures("_project")
class TestEntry:
    # Bare `vekna` is the daemon and blocks, so what is checked here is that
    # the tree is reachable — the daemon itself is exercised in test_daemon.py.
    @staticmethod
    def test_the_help_lists_the_commands():
        result = CliRunner().invoke(init_command(), ["--help"])

        assert not result.exit_code
        listed = {
            line.strip().split(maxsplit=1)[0]
            for line in result.output.splitlines()
            if line.startswith("  ") and line.strip()
        }
        assert {"cast", "log", "rituals"} <= listed

    @staticmethod
    def test_casting_a_ritual_reaches_the_runtime():
        result = CliRunner().invoke(
            init_command(), ["cast", "countdown", "--start", "1"]
        )

        assert not result.exit_code

    @staticmethod
    def test_casting_a_ritual_that_does_not_exist_is_a_usage_error():
        result = CliRunner().invoke(init_command(), ["cast", "invented"])

        assert result.exit_code == _USAGE_EXIT

    @staticmethod
    def test_listing_rituals_reaches_the_runtime():
        result = CliRunner().invoke(init_command(), ["rituals", "list"])

        assert not result.exit_code
        assert "countdown" in result.output

    @staticmethod
    def test_showing_a_ritual_reaches_the_runtime():
        result = CliRunner().invoke(init_command(), ["rituals", "show", "countdown"])

        assert not result.exit_code
        assert "countdown" in result.output
