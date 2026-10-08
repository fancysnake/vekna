import asyncio
import io
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import BaseModel, JsonValue
from typing_extensions import override

from tests.conftest import entry, journalled
from vekna.folio.shell import ShellOutputError, ShellResult, shell
from vekna.folio.shell._links import run_bash
from vekna.lexicon import (
    SHELL_FOCUS,
    Done,
    RiteTimeoutError,
    ShellCall,
    ShellFocusProtocol,
    ShellReply,
    step,
    timeout,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed, Ritual

_FAILURE_EXIT = 3
# `read` meeting EOF straight away.
_EOF_EXIT = 1
# Comfortably past the 1 MiB readline limit that used to crash the cast here.
_LONG_LINE = 2_000_000
# The ↳ that opens a rite and the ✓ that closes it, both quoting the command.
_RITE_LINES = 2
# The bash a cancelled `shell` ran, and the child it left in the background.
_SPAWNED = 2


class Echo(BaseModel):
    pass


class Fail(BaseModel):
    pass


class Quiet(BaseModel):
    pass


class QuietPartial(BaseModel):
    pass


class ReadsStdin(BaseModel):
    pass


class LongLine(BaseModel):
    pass


class PartialLine(BaseModel):
    pass


class Multibyte(BaseModel):
    pass


@step
async def run_echo(_state: Echo) -> Done[ShellResult]:
    return Done(await shell("echo hello && exit 0"))


@step
async def run_fail(_state: Fail) -> Done[ShellResult]:
    return Done(await shell("echo oops >&2; exit 3"))


@step
async def run_quiet(_state: Quiet) -> Done[ShellResult]:
    return Done(await shell("echo hush", stream=False))


@step
async def run_quiet_partial(_state: QuietPartial) -> Done[ShellResult]:
    # Silent *and* without a trailing newline: the tail of the last chunk has
    # no `on_line` to reach, which is the one path the two apart never take.
    return Done(await shell("printf 'hushed'", stream=False))


@step
async def run_reads_stdin(_state: ReadsStdin) -> Done[ShellResult]:
    return Done(await shell('read -r line && echo "got $line"'))


@step
async def run_long_line(_state: LongLine) -> Done[ShellResult]:
    return Done(
        await shell(f"python3 -c \"print('x' * {_LONG_LINE}); print('after')\"")
    )


@step
async def run_partial_line(_state: PartialLine) -> Done[ShellResult]:
    return Done(await shell("printf 'no newline'"))


@step
async def run_multibyte(_state: Multibyte) -> Done[ShellResult]:
    # Split across chunk boundaries, so an incremental decoder is the only way
    # these survive intact.
    return Done(await shell(f"python3 -c \"print('☃' * {_LONG_LINE})\""))


echoer = entry(name="echoer", payload=Echo())
failing = entry(name="failing", payload=Fail())
quiet = entry(name="quiet", payload=Quiet())
quiet_partial = entry(name="quiet_partial", payload=QuietPartial())
long_line = entry(name="long_line", payload=LongLine())
partial_line = entry(name="partial_line", payload=PartialLine())
multibyte = entry(name="multibyte", payload=Multibyte())
reads_stdin = entry(name="reads_stdin", payload=ReadsStdin())


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


class _RecordingFocus(ShellFocusProtocol):
    def __init__(self) -> None:
        self.intercepted: list[ShellCall] = []

    @override
    async def run(
        self, call: ShellCall, *, on_line: Callable[[str], None] | None
    ) -> ShellReply:
        self.intercepted.append(call)
        if on_line is not None:
            on_line("intercepted")
        return ShellReply(stdout="from the focus", stderr="", exit_code=0)


# Swapping fd 0 for real is the only honest way to prove a command cannot reach
# it — mocking `create_subprocess_exec` would assert the implementation back at
# itself. It is process-global state, so every fd is restored and closed even
# when the cast raises, which is exactly what a regression here does.
@contextmanager
def _typed_at_stdin(text: bytes) -> Iterator[int]:
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, text)
        os.close(write_fd)
        stdin_fd = os.dup(0)
        try:
            os.dup2(read_fd, 0)
            yield read_fd
        finally:
            os.dup2(stdin_fd, 0)
            os.close(stdin_fd)
    finally:
        os.close(read_fd)


class TestShellStdin:
    # The bug this holds shut: a command inheriting the terminal reads the line
    # the operator typed at a prompt beside it, and the answer disappears.
    @staticmethod
    def test_a_command_cannot_read_what_the_operator_typed():
        with _typed_at_stdin(b"1\n") as read_fd:
            result = _cast(reads_stdin)
            unread = os.read(read_fd, 2)

        assert (result.exit_code, result.stdout, unread) == (_EOF_EXIT, "", b"1\n")


class TestShellFocus:
    @staticmethod
    def test_a_registered_focus_answers_instead_of_bash():
        focus = _RecordingFocus()

        with SHELL_FOCUS.scope(focus):
            result, grimoire, _ = _run(echoer)

        assert result == ShellResult(stdout="from the focus", stderr="", exit_code=0)
        assert [call.command for call in focus.intercepted] == ["echo hello && exit 0"]
        assert _deltas(grimoire) == ["intercepted"]

    @staticmethod
    def test_bash_answers_again_once_the_scope_closes():
        with SHELL_FOCUS.scope(_RecordingFocus()):
            pass

        assert _cast(echoer).stdout.strip() == "hello"


class Spawning(BaseModel):
    pids: str


# Writes its own pid and a background child's, then waits on the child — the
# shape a cancelled `bash -c` used to leave running.
@step
async def spawning(state: Spawning) -> Done[ShellResult]:
    command = f"sleep 300 & echo $$ $! > {state.pids}; wait"
    return Done(await timeout(shell(command), seconds=0.5))


# A zombie is still in `/proc`, and is not running anything.
def _running(pid: str) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


class TestCancelledShell:
    @staticmethod
    def test_a_timed_out_command_leaves_no_process_behind(tmp_path):
        pids = tmp_path / "pids"
        the_ritual = entry(name="spawning", payload=Spawning(pids=str(pids)))
        grimoire = Grimoire(cast_id="c1")

        with pytest.raises(RiteTimeoutError, match=r"^shell timed out after 0\.5s$"):
            asyncio.run(
                run_cast(
                    ritual=the_ritual,
                    components=the_ritual.components(),
                    grimoire=grimoire,
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                )
            )

        started = pids.read_text(encoding="utf-8").split()
        assert len(started) == _SPAWNED
        assert not [pid for pid in started if _running(pid)]
        names = {
            event.rite_id: event.name
            for event in grimoire.events
            if isinstance(event, RiteBegan)
        }
        assert [
            (names[event.rite_id], event.status)
            for event in grimoire.events
            if isinstance(event, RiteEnded)
        ] == [("shell", "cancelled"), ("spawning", "error")]


class Stubborn(BaseModel):
    pids: str


# Ignores SIGTERM, so only the escalation ends it.
@step
async def stubborn(state: Stubborn) -> Done[ShellResult]:
    command = f"trap '' TERM; echo $$ > {state.pids}; sleep 300 & wait"
    return Done(await timeout(shell(command), seconds=0.5))


class TestStubbornShell:
    @staticmethod
    def test_a_command_ignoring_sigterm_is_killed(tmp_path):
        pids = tmp_path / "pids"
        the_ritual = entry(name="stubborn", payload=Stubborn(pids=str(pids)))

        with pytest.raises(RiteTimeoutError):
            asyncio.run(
                run_cast(
                    ritual=the_ritual,
                    components=the_ritual.components(),
                    grimoire=Grimoire(cast_id="c1"),
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                )
            )

        assert not _running(pids.read_text(encoding="utf-8").strip())

    @staticmethod
    def test_a_second_cancel_in_the_grace_window_still_kills_the_group(tmp_path):
        pids = tmp_path / "pids"
        command = f"trap '' TERM; sleep 300 & echo $$ $! > {pids}; wait"

        async def cancel_twice() -> None:
            running = asyncio.create_task(run_bash(command))
            await asyncio.sleep(0.5)
            running.cancel()
            await asyncio.sleep(0.2)
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running

        asyncio.run(cancel_twice())

        started = pids.read_text(encoding="utf-8").split()
        assert len(started) == _SPAWNED
        assert not [pid for pid in started if _running(pid)]
