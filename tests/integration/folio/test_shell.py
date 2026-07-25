import asyncio
import io

from pydantic import BaseModel

from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import Transition, done, goto, ritual, step
from vekna.lexicon.entry import Grimoire, Ritual, StandaloneRenderer, run_cast
from vekna.wire import RiteDelta

_FAILURE_EXIT = 3
# Comfortably past the 1 MiB readline limit that used to crash the cast here.
_LONG_LINE = 2_000_000


class State(BaseModel):
    pass


@step
async def run_echo(_state: State) -> Transition:
    return done(await shell("echo hello && exit 0"))


@step
async def run_fail(_state: State) -> Transition:
    return done(await shell("echo oops >&2; exit 3"))


@step
async def run_quiet(_state: State) -> Transition:
    return done(await shell("echo hush", stream=False))


@step
async def run_long_line(_state: State) -> Transition:
    return done(
        await shell(f"python3 -c \"print('x' * {_LONG_LINE}); print('after')\"")
    )


@step
async def run_multibyte(_state: State) -> Transition:
    # Split across chunk boundaries, so an incremental decoder is the only way
    # these survive intact.
    return done(await shell(f"python3 -c \"print('☃' * {_LONG_LINE})\""))


@ritual("echoer")
async def echoer() -> Transition:
    await asyncio.sleep(0)
    return goto(run_echo, State())


@ritual("failing")
async def failing() -> Transition:
    await asyncio.sleep(0)
    return goto(run_fail, State())


@ritual("quiet")
async def quiet() -> Transition:
    await asyncio.sleep(0)
    return goto(run_quiet, State())


@ritual("long_line")
async def long_line() -> Transition:
    await asyncio.sleep(0)
    return goto(run_long_line, State())


@ritual("multibyte")
async def multibyte() -> Transition:
    await asyncio.sleep(0)
    return goto(run_multibyte, State())


def _run(the_ritual: Ritual) -> tuple[ShellResult, Grimoire, io.StringIO]:
    out = io.StringIO()
    renderer = StandaloneRenderer(out=out, inp=io.StringIO())
    grimoire = Grimoire(cast_id="c1", on_event=renderer.render)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=renderer,
        )
    )
    assert isinstance(result, ShellResult)
    return result, grimoire, out


def _cast(the_ritual: Ritual) -> ShellResult:
    result, _, _ = _run(the_ritual)
    return result


def _deltas(grimoire: Grimoire) -> list[str]:
    return [event.delta for event in grimoire.events if isinstance(event, RiteDelta)]


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


class TestShellStreaming:
    @staticmethod
    def test_stdout_streams_into_the_rite_and_renders():
        result, grimoire, out = _run(echoer)

        assert _deltas(grimoire) == ["hello"]
        assert "hello" in out.getvalue()
        # Streaming does not cost the caller the captured output.
        assert result.stdout.strip() == "hello"

    @staticmethod
    def test_stderr_streams_too():
        _, grimoire, out = _run(failing)

        assert _deltas(grimoire) == ["oops"]
        assert "oops" in out.getvalue()

    @staticmethod
    def test_a_line_past_the_old_limit_does_not_crash_the_cast():
        result, grimoire, _ = _run(long_line)

        assert not result.exit_code
        assert result.stdout == f"{'x' * _LONG_LINE}\nafter\n"
        assert _deltas(grimoire) == ["x" * _LONG_LINE, "after"]

    @staticmethod
    def test_multibyte_output_survives_chunk_boundaries():
        result = _cast(multibyte)

        assert not result.exit_code
        assert result.stdout == f"{'☃' * _LONG_LINE}\n"

    @staticmethod
    def test_stream_false_stays_silent():
        result, grimoire, out = _run(quiet)

        assert not _deltas(grimoire)
        assert "hush" not in out.getvalue()
        assert result.stdout.strip() == "hush"
