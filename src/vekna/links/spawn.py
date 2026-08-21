import asyncio
import contextlib
import signal
from asyncio.subprocess import DEVNULL, PIPE
from collections.abc import Sequence

# How long a cast is given to end on its own after being asked. A ritual that is
# mid-shell-command needs a moment; one that is wedged does not get to keep the
# slot for it.
_GRACE_SECONDS = 5.0
# The tail of what a cast wrote to stderr, kept so a non-zero exit can say why.
# The whole stream is the journal's — the cast reports itself to the daemon.
_STDERR_LINES = 20


# A process that outlives the shell that asked for it. `start_new_session` is
# the whole of it: a lich raised over ssh must not die with the session, and a
# process group of its own is what stops the hangup reaching it.
# Nothing is piped — a lich reports itself over the socket, and a stream nobody
# reads is a pipe that fills up and blocks the process behind it.
# The parent does not wait: it has raised the thing and its job is done, and
# `init` is what reaps a child whose parent went away.
async def raise_detached(*, argv: Sequence[str], cwd: str) -> int:
    detached = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=DEVNULL,
        stdout=DEVNULL,
        stderr=DEVNULL,
        start_new_session=True,
    )
    return detached.pid


# The cast a lich is running, and the three things a lich does with it: wait for
# it, answer the question it is blocked on, and kill it.
# Its stdin is a pipe, which is the whole of how a decide is answered from
# somewhere else: the cast keeps the reader it always had — one blocking read of
# one stream — and what changes is who is on the other end of it. Nothing races
# the terminal, because there is no terminal.
class CastProcess:
    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._tail: list[str] = []

    @property
    def pid(self) -> int:
        return self._process.pid

    # Written and not awaited: the lich's command loop must not block on a cast
    # that has stopped reading, and a `decide` that is no longer open is a line
    # into a pipe nobody reads rather than a lich that stops answering.
    def answer(self, line: str) -> None:
        if (stdin := self._process.stdin) is not None and not stdin.is_closing():
            stdin.write(f"{line}\n".encode())

    async def wait(self) -> int:
        reading = asyncio.create_task(self._read_stderr())
        code = await self._process.wait()
        await reading
        return code

    @property
    def stderr_tail(self) -> str:
        return "\n".join(self._tail)

    # Asked first, and taken at its word for a while: a cast mid-command has a
    # subprocess of its own to end, and a `SIGKILL` straight away would leave
    # that one running with nobody holding it.
    async def kill(self) -> None:
        if self._process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            self._process.send_signal(signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._process.wait(), timeout=_GRACE_SECONDS)
            return
        with contextlib.suppress(ProcessLookupError):
            self._process.kill()

    async def _read_stderr(self) -> None:
        if (stderr := self._process.stderr) is None:
            return
        with contextlib.suppress(ValueError, OSError):
            async for raw in stderr:
                self._tail.append(raw.decode(errors="replace").rstrip())
                del self._tail[:-_STDERR_LINES]


# A cast the lich is responsible for. stdout goes nowhere on purpose: the cast
# reports itself to the daemon over its own connection, so a second copy of the
# same tree down a pipe would be read by nobody and fill up.
async def spawn_cast(
    *, argv: Sequence[str], cwd: str, env: dict[str, str]
) -> CastProcess:
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=PIPE, stdout=DEVNULL, stderr=PIPE
    )
    return CastProcess(process)
