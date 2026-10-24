import asyncio
import contextlib
import fcntl
import sys
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import IO
from uuid import uuid4

import click

from vekna.links.circle_config import ConfigLimits
from vekna.links.debug_log import DebugLog
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach, serve
from vekna.links.spawner import Spawner, pid_alive
from vekna.links.worktrees import GitTrees
from vekna.mills.circle import Awaits, Circle, CodingPool, Leasing, LeftBehind
from vekna.mills.debug import debug_line
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed, Routes, Surface
from vekna.wire import (
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastRefused,
    CastRequested,
    CodingSlotReleased,
    CodingSlotRequested,
    DecideClaimed,
    DecideResolved,
    EnqueueAccepted,
    EnqueueRefused,
    EnqueueRequested,
    StopRequested,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
    project_of,
)

# Spawned through the interpreter running this one rather than through whatever
# `vekna` is on PATH, which in a venv, a `pipx` install or a test is not always
# the same binary.
CLI_MODULE = "vekna.inits.cli"
# What the daemon spawns a cast with: no terminal, so prompts come over the wire.
_CAST_COMMAND = (sys.executable, "-m", CLI_MODULE, "cast", "--wired")
# What the daemon keeps on disk, trimmed once at startup rather than on every
# write: a cast is a directory of a few kilobytes, and this is about a machine
# that has been running vekna for a year, not about the last hour.
_KEPT = 200
_DAEMON_LOG = "daemon.log"
# Out of the way of editors and `mise`, which would trip over a tree in the
# project.
_WORKTREES = "worktrees"
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
    limits = ConfigLimits(say=_logged)
    spawner = Spawner(command=_CAST_COMMAND, runs=default_runs_root())
    if spawned := await asyncio.to_thread(spawner.left_behind):
        _logged(f"holding {len(spawned)} cast(s) left running until they reattach")
    left = LeftBehind(casts=hub, spawned=spawned, alive=pid_alive)
    leasing = Leasing(
        left=left,
        say=_logged,
        spawn=spawner,
        trees=GitTrees(root=default_state_root() / _WORKTREES),
        limits=limits,
    )
    circle = Circle(
        hub=hub,
        left=left,
        leasing=leasing,
        limits=limits,
        awaits=Awaits(hub=hub, records=journal.read),
    )
    # What a stopped daemon left waiting, less what it had already spawned.
    running = {left_over.cast_id for left_over in spawned}
    for record in await asyncio.to_thread(journal.queued):
        if record.hello.cast_id not in running:
            circle.enqueue(record.hello)
    pool = CodingPool(tell=hub.tell, limits=limits)
    server = await serve(path=path, routes=_Daemon(hub=hub, circle=circle, pool=pool))
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


# The hub, the circle and the coding pool behind one socket: the hub holds what
# every cast is doing, the circle what may run next, the pool who is talking to
# an agent. Slot traffic is the pool's alone, and an ending is everyone's.
class _Daemon(Routes):
    def __init__(self, *, hub: Hub, circle: Circle, pool: CodingPool) -> None:
        self._hub = hub
        self._circle = circle
        self._pool = pool
        self._tasks: set[asyncio.Task[None]] = set()

    def apply(self, message: CastMessage) -> None:
        if isinstance(message, CodingSlotRequested):
            self._pool.requested(message)
        elif isinstance(message, CodingSlotReleased):
            self._pool.released(message)
        elif isinstance(message, EnqueueRequested):
            self._settled(
                self._enqueued(message),
                ritual=message.hello.ritual,
                refuse=lambda reason: self._refuse(message, reason),
            )
        else:
            self._hub.apply(message)
            if isinstance(message, CastGoodbye):
                self._pool.ended(message.cast_id)
            if isinstance(message, (CastGoodbye, AwaitRequested, AwaitWithdrawn)):
                self._circle.wake()

    # The hello is the enqueuing cast's; all that is checked here is that the
    # tree it names is still there to spawn in.
    async def _enqueued(self, request: EnqueueRequested) -> None:
        if (reason := await _missing(request.hello.project_root)) is not None:
            self._refuse(request, reason)
            return
        self._circle.enqueue(request.hello)
        accepted = EnqueueAccepted(
            cast_id=request.cast_id, request_id=request.request_id
        )
        self._hub.tell(request.cast_id, accepted)

    def _refuse(self, request: EnqueueRequested, reason: str) -> None:
        refused = EnqueueRefused(
            cast_id=request.cast_id, request_id=request.request_id, reason=reason
        )
        self._hub.tell(request.cast_id, refused)

    # A task of its own, so the read loop the request came in on is not held
    # up. Whatever it raises is logged and refused to whoever asked, who would
    # otherwise wait on an answer that never comes.
    def _settled(
        self,
        work: Coroutine[None, None, None],
        *,
        ritual: str,
        refuse: Callable[[str], None],
    ) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        def settled(done: asyncio.Task[None]) -> None:
            if done.cancelled() or (error := done.exception()) is None:
                return
            reason = f"could not queue {ritual}: {error}"
            _logged(reason)
            refuse(reason)

        task.add_done_callback(settled)

    def attach_surface(self, surface: Surface) -> None:
        self._hub.attach_surface(surface)

    def detach_surface(self, surface: Surface) -> None:
        self._hub.detach_surface(surface)

    def answer(self, surface: Surface, resolved: DecideResolved) -> None:
        self._hub.answer(surface, resolved)

    def claim(self, surface: Surface, claimed: DecideClaimed) -> None:
        self._hub.claim(surface, claimed)

    def open_cast(self, cast_id: str, peer: Surface) -> None:
        self._hub.open_cast(cast_id, peer)

    def close_cast(self, cast_id: str, peer: Surface) -> None:
        self._hub.close_cast(cast_id, peer)

    # Resolving the project asks git, so it is not done in the read loop.
    def request(self, surface: Surface, request: CastRequested) -> None:
        self._settled(
            self._queued(surface, request),
            ritual=request.ritual,
            refuse=lambda reason: surface.send(CastRefused(reason=reason)),
        )

    async def _queued(self, surface: Surface, request: CastRequested) -> None:
        if (reason := await _missing(request.project_root)) is not None:
            surface.send(CastRefused(reason=reason))
            return
        root = Path(request.project_root)
        self._circle.enqueue(
            CastHello(
                cast_id=uuid4().hex,
                project_root=str(root),
                project=await project_of(root),
                ritual=request.ritual,
                components=dict(request.components),
                started_at=datetime.now(tz=UTC),
                wired=True,
            )
        )


# Why a cast cannot be queued in `root`, or `None` once it can: the tree has to
# be there to spawn in.
async def _missing(root: str) -> str | None:
    if await asyncio.to_thread(Path(root).is_dir):
        return None
    return f"{root} is not a directory"
