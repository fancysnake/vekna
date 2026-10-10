import asyncio
import contextlib
import fcntl
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

import click

from vekna.links.debug_log import DebugLog
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach, serve
from vekna.mills.debug import debug_line
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed
from vekna.wire import (
    StopRequested,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
)

# Spawned through the interpreter running this one rather than through whatever
# `vekna` is on PATH, which in a venv, a `pipx` install or a test is not always
# the same binary.
CLI_MODULE = "vekna.inits.cli"
# What the daemon keeps on disk, trimmed once at startup rather than on every
# write: a cast is a directory of a few kilobytes, and this is about a machine
# that has been running vekna for a year, not about the last hour.
_KEPT = 200
_DAEMON_LOG = "daemon.log"
_LOCK_SUFFIX = ".lock"
_NO_DAEMON = "no daemon running"
_STOPPED = "stopped the daemon"
# How long a daemon gets to start listening, and to stop.
_POLL_SECONDS = 0.05
_POLLS = 100


def _nothing(_: Routed) -> None:
    pass


def _sink(debug: Path | None) -> Callable[[Routed], None]:
    if debug is None:
        return _nothing
    log = DebugLog(debug)

    def record(routed: Routed) -> None:
        log.write(debug_line(routed))

    return record


# Said into `daemon.log`, which is where a detached daemon's stderr goes: there
# is no view of its own to say it on.
def _logged(note: str) -> None:
    click.echo(
        f"{datetime.now(tz=UTC).astimezone():%Y-%m-%d %H:%M:%S} {note}", err=True
    )


# The daemon itself, with no view: it binds, journals, fans out, and runs until
# `vekna stop` asks it not to. Refuses rather than binds when another one holds
# the lock, since a bind would take the socket from under it.
# The lock sits beside the socket it guards, so a daemon on a socket of its own
# never contends with this one. The kernel lets go of it however the holder
# ends, so there is never a stale one to clear.
async def serve_daemon(*, debug: Path | None = None) -> int:
    path = default_socket_path()
    lock = path.with_name(path.name + _LOCK_SUFFIX)
    await asyncio.to_thread(lock.parent.mkdir, parents=True, exist_ok=True)
    with lock.open("a", encoding="utf-8") as held:
        if not _locked(held):
            _logged(f"another daemon holds {lock}")
            return 1
        return await _serving(path=path, debug=debug)


def _locked(held: IO[str]) -> bool:
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


async def _serving(*, path: Path, debug: Path | None) -> int:
    journal = Journal(default_runs_root())
    hub = Hub(on_routed=_sink(debug), on_journal=journal.record)
    if debug is not None:
        _logged(f"logging every event to {debug}")
    # Before the socket binds, so nothing is being written while it runs.
    if failed := await asyncio.to_thread(journal.prune, keep=_KEPT):
        _logged(f"could not prune {len(failed)} old cast(s): {failed[0]}")
    server = await serve(
        path=path,
        on_message=hub.apply,
        on_attach=hub.attach_surface,
        on_detach=hub.detach_surface,
    )
    _logged(f"listening on {path}")
    try:
        await server.stopped()
    finally:
        await server.close()
    _logged("stopped")
    return 0


# `vekna serve` detaches itself and its launcher exits at once, so what is
# awaited here is the launch; whether the daemon came up is the socket's to say.
async def summon(*, path: Path, debug: bool) -> None:
    log = default_state_root() / _DAEMON_LOG
    await asyncio.to_thread(log.parent.mkdir, parents=True, exist_ok=True)
    flags = ["--debug"] if debug else []
    with log.open("ab") as out:
        launched = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            CLI_MODULE,
            "serve",
            *flags,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=out,
            stderr=asyncio.subprocess.STDOUT,
        )
        code = await launched.wait()
    if code != 0:
        message = f"the daemon would not start ({code}) — {log} says why"
        raise click.ClickException(message)
    if not await _until(path, listening=True):
        message = f"the daemon is not listening on {path} — {log} says why"
        raise click.ClickException(message)


# Whether the socket came to answer, or stopped answering, in the time a daemon
# gets to start or to stop.
async def _until(path: Path, *, listening: bool) -> bool:
    for _ in range(_POLLS):
        if await alive(path) is listening:
            return True
        await asyncio.sleep(_POLL_SECONDS)
    return False


# Waits for the socket to stop answering, so `vekna stop && vekna` starts a
# fresh daemon rather than attaching to the one on its way out.
# Only a socket that is not there, or that nobody listens on, is no daemon: one
# that refuses this account or will not answer in time is a daemon in trouble.
async def stop_daemon() -> str:
    path = default_socket_path()
    try:
        _, writer = await attach(path)
    except (FileNotFoundError, ConnectionRefusedError):
        return _NO_DAEMON
    except OSError as error:
        message = f"could not reach the daemon on {path}: {error!r}"
        raise click.ClickException(message) from error
    writer.write(encode_frame(StopRequested()))
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    if not await _until(path, listening=False):
        message = f"asked the daemon to stop, and {path} is still answering"
        raise click.ClickException(message)
    return _STOPPED
