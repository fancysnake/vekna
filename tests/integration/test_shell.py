import asyncio
import io

from pydantic import BaseModel

from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import (
    Grimoire,
    Ritual,
    StandaloneRenderer,
    Transition,
    done,
    goto,
    ritual,
    run_cast,
    step,
)

_FAILURE_EXIT = 3


class State(BaseModel):
    pass


@step
async def run_echo(_state: State) -> Transition:
    return done(await shell("echo hello && exit 0"))


@step
async def run_fail(_state: State) -> Transition:
    return done(await shell("echo oops >&2; exit 3"))


@ritual("echoer")
async def echoer() -> Transition:
    await asyncio.sleep(0)
    return goto(run_echo, State())


@ritual("failing")
async def failing() -> Transition:
    await asyncio.sleep(0)
    return goto(run_fail, State())


def _cast(the_ritual: Ritual) -> ShellResult:
    grimoire = Grimoire(cast_id="c1")
    renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=renderer,
        )
    )
    assert isinstance(result, ShellResult)
    return result


class TestShell:
    @staticmethod
    def test_captures_stdout_and_zero_exit():
        result = _cast(echoer)

        assert result.stdout.strip() == "hello"
        assert not result.exit_code

    @staticmethod
    def test_captures_stderr_and_nonzero_exit():
        result = _cast(failing)

        assert result.stderr.strip() == "oops"
        assert result.exit_code == _FAILURE_EXIT
