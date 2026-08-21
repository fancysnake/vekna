import asyncio
from asyncio.subprocess import DEVNULL
from collections.abc import Sequence


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
