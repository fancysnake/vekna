import asyncio
import io

import pytest
from pydantic import BaseModel, JsonValue

from tests.conftest import entry, journalled
from vekna.folio.shell import ShellOutputError, ShellResult, shell
from vekna.lexicon import (
    SHELL_FOCUS,
    ShellCall,
    ShellFocusProtocol,
    ShellReply,
    Transition,
    done,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast
from vekna.lexicon._pacts import RiteStreamed, Ritual

_FAILURE_EXIT = 3
# Comfortably past the 1 MiB readline limit that used to crash the cast here.
_LONG_LINE = 2_000_000
# The ↳ that opens a rite and the ✓ that closes it, both quoting the command.
_RITE_LINES = 2


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
async def run_quiet_partial(_state: State) -> Transition:
    # Silent *and* without a trailing newline: the tail of the last chunk has
    # no `on_line` to reach, which is the one path the two apart never take.
    return done(await shell("printf 'hushed'", stream=False))


@step
async def run_long_line(_state: State) -> Transition:
    return done(
        await shell(f"python3 -c \"print('x' * {_LONG_LINE}); print('after')\"")
    )


@step
async def run_partial_line(_state: State) -> Transition:
    return done(await shell("printf 'no newline'"))


@step
async def run_multibyte(_state: State) -> Transition:
    # Split across chunk boundaries, so an incremental decoder is the only way
    # these survive intact.
    return done(await shell(f"python3 -c \"print('☃' * {_LONG_LINE})\""))


echoer = entry(name="echoer", target=run_echo, payload=State())
failing = entry(name="failing", target=run_fail, payload=State())
quiet = entry(name="quiet", target=run_quiet, payload=State())
quiet_partial = entry(name="quiet_partial", target=run_quiet_partial, payload=State())
long_line = entry(name="long_line", target=run_long_line, payload=State())
partial_line = entry(name="partial_line", target=run_partial_line, payload=State())
multibyte = entry(name="multibyte", target=run_multibyte, payload=State())


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


def _resumed(recorded: JsonValue) -> object:
    renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())
    return asyncio.run(
        run_cast(
            ritual=echoer,
            components=echoer.components(),
            grimoire=Grimoire(cast_id="c1"),
            channel=renderer,
            ledger=journalled(recorded, name="shell"),
        )
    )


class TestResumedRites:
    # `echo hello` never runs: what comes back is what the interrupted cast
    # recorded, which is the whole point of not re-running a shell command.
    @staticmethod
    def test_a_command_that_already_ran_comes_off_the_journal():
        recorded = {"stdout": "from the journal\n", "stderr": "", "exit_code": 0}

        assert _resumed(recorded) == ShellResult(
            stdout="from the journal\n", stderr="", exit_code=0
        )

    @staticmethod
    def test_a_journal_holding_something_else_says_so():
        with pytest.raises(ShellOutputError, match="journaled as something else"):
            _resumed({"text": "that was a coding rite"})


def _deltas(grimoire: Grimoire) -> list[str]:
    return [event.delta for event in grimoire.events if isinstance(event, RiteStreamed)]


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
    def test_output_without_a_trailing_newline_is_kept_and_streamed():
        result, grimoire, out = _run(partial_line)

        assert result.stdout == "no newline"
        assert _deltas(grimoire) == ["no newline"]
        assert "no newline" in out.getvalue()

    @staticmethod
    def test_multibyte_output_survives_chunk_boundaries():
        result = _cast(multibyte)

        assert not result.exit_code
        assert result.stdout == f"{'☃' * _LONG_LINE}\n"

    @staticmethod
    def test_stream_false_stays_silent():
        result, grimoire, out = _run(quiet)

        assert not _deltas(grimoire)
        # Counted, not matched: the command is quoted in the rite's own two
        # lines, so what has to stay off the surface is the *output* — and here
        # the two are the same word. The tree's format is the renderer's test.
        assert out.getvalue().count("hush") == _RITE_LINES
        assert result.stdout.strip() == "hush"

    @staticmethod
    def test_stream_false_still_keeps_a_partial_last_line():
        result, grimoire, out = _run(quiet_partial)

        assert not _deltas(grimoire)
        assert out.getvalue().count("hushed") == _RITE_LINES
        assert result.stdout == "hushed"


# A Focus is static — it carries no per-call state — so what it records lives
# beside it rather than on it.
_intercepted: list[ShellCall] = []


class _RecordingFocus(ShellFocusProtocol):
    @staticmethod
    async def run(call, *, on_line):
        _intercepted.append(call)
        if on_line is not None:
            on_line("intercepted")
        return ShellReply(stdout="from the focus", stderr="", exit_code=0)


class TestShellFocus:
    @staticmethod
    def test_a_registered_focus_answers_instead_of_bash():
        _intercepted.clear()

        with SHELL_FOCUS.scope(_RecordingFocus):
            result, grimoire, _ = _run(echoer)

        assert result == ShellResult(stdout="from the focus", stderr="", exit_code=0)
        assert [call.command for call in _intercepted] == ["echo hello && exit 0"]
        assert _deltas(grimoire) == ["intercepted"]

    @staticmethod
    def test_bash_answers_again_once_the_scope_closes():
        with SHELL_FOCUS.scope(_RecordingFocus):
            pass

        assert _cast(echoer).stdout.strip() == "hello"
