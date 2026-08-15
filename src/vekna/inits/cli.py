import asyncio
import contextlib
import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import click
from click import Group

from vekna.gates.cli.dashboard import Dashboard
from vekna.gates.cli.screen import listing
from vekna.links.debug_log import DebugLog
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach, serve
from vekna.links.terminal import Terminal
from vekna.mills.debug import debug_line
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed
from vekna.pacts.screen import Screen
from vekna.wire import (
    CastMessage,
    SurfaceHello,
    default_runs_root,
    default_socket_path,
    encode_frame,
    read_frames,
)

_CAST_CONTEXT: dict[str, bool] = {"ignore_unknown_options": True}
_RUNTIME = "vekna.lexicon._inits"
# Spawned through the interpreter running this one rather than through whatever
# `vekna` is on PATH, which in a venv, a `pipx` install or a test is not always
# the same binary.
_CLI_MODULE = "vekna.inits.cli"
_RESUME = "--resume"
_RECENT = 20
# What the daemon keeps on disk, trimmed once at startup rather than on every
# write: a cast is a directory of a few kilobytes, and this is about a machine
# that has been running vekna for a year, not about the last hour.
_KEPT = 200
_DEBUG_LOG = Path.home() / ".config" / "vekna" / "debug.log"
_DAEMON_ENDED = "the daemon ended"
_PEER = "attached to the vekna already running here"


# The root project may not import the lexicon: `vekna` (daemon) and `vekna cast`
# are one binary, so importing the CLI must never pull ritual code, folios or
# the agent SDK into the daemon's process. The cast runtime is reached by name
# at call time, and typed through this Protocol rather than by attribute access
# on an untyped module.
class _Runtime(Protocol):
    @staticmethod
    def main(argv: list[str]) -> int: ...
    @staticmethod
    def rituals_list() -> int: ...
    @staticmethod
    def rituals_show(name: str) -> int: ...


def _runtime() -> _Runtime:
    return cast("_Runtime", importlib.import_module(_RUNTIME))


@click.command(
    "cast",
    context_settings=_CAST_CONTEXT,
    add_help_option=False,
    help="Run a ritual from rituals.py (try `vekna cast --help`).",
)
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(ritual_args: tuple[str, ...]) -> None:
    raise SystemExit(_runtime().main(list(ritual_args)))


@click.command("list", help="List rituals and the options each one takes.")
def _rituals_list() -> None:
    raise SystemExit(_runtime().rituals_list())


@click.command("show", help="Show a ritual's components and step graph.")
@click.argument("name")
def _rituals_show(name: str) -> None:
    raise SystemExit(_runtime().rituals_show(name))


@click.group("rituals", help="Inspect the ritual library.")
def _rituals() -> None:
    pass


async def _spawn_cast(cast_id: str, *, cwd: str) -> int:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", _CLI_MODULE, "cast", _RESUME, cast_id, cwd=cwd
    )
    return await process.wait()


@click.command("list", help="List the casts the daemon has seen, newest first.")
def _casts_list() -> None:
    records = Journal(default_runs_root()).recent(limit=_RECENT)
    click.echo(listing(records), nl=False)


# Always a fresh process, in the directory the interrupted cast ran in: the
# ritual source is found by walking up from there, and a resume that ran here
# would cast a different project's ritual of the same name. The journal is
# handed over by name — the cast process reads it itself, being the only one
# that needs what is in it.
@click.command("resume", help="Run a cast on from where it was interrupted.")
@click.argument("cast_id")
def _casts_resume(cast_id: str) -> None:
    if (record := Journal(default_runs_root()).read(cast_id)) is None:
        message = f"no cast {cast_id!r} in the journal — `vekna casts list` has the ids"
        raise click.ClickException(message)
    # The directory is the record's, not this shell's, and a project that has
    # been moved or deleted since is the likeliest thing to have gone wrong
    # between the two casts. Said as a sentence naming it, rather than as the
    # `NotADirectoryError` the spawn would otherwise raise from inside asyncio.
    root = record.hello.project_root
    if not Path(root).is_dir():
        message = f"{root} is not there any more — cast {cast_id!r} ran in it"
        raise click.ClickException(message)
    raise SystemExit(asyncio.run(_spawn_cast(cast_id, cwd=root)))


@click.group("casts", invoke_without_command=True, help="The casts on record.")
def _casts() -> None:
    ctx = click.get_current_context()
    if ctx.invoked_subcommand is None:
        ctx.invoke(_casts_list)


_casts.add_command(_casts_list)
_casts.add_command(_casts_resume)


_rituals.add_command(_rituals_list)
_rituals.add_command(_rituals_show)


def _nothing(_: Routed) -> None:
    pass


def _sink(debug: Path | None) -> Callable[[Routed], None]:
    if debug is None:
        return _nothing
    log = DebugLog(debug)

    def record(routed: Routed) -> None:
        log.write(debug_line(routed))

    return record


# A second `vekna` in the same account is a surface on the first: it says so, is
# replayed every live cast, and paints the same view. It journals nothing — the
# daemon that owns the socket owns the record.
async def _as_peer(*, path: Path, screen: Screen) -> int:
    reader, writer = await attach(path)
    writer.write(encode_frame(SurfaceHello()))
    hub = Hub()
    dashboard = Dashboard(casts=hub, screen=screen)
    dashboard.say(_PEER)

    # What a daemon sends a surface is what it heard from its casts, so the
    # handshake this end wrote is the only frame kind that cannot come back.
    async def listen() -> None:
        async for message in read_frames(reader):
            if isinstance(message, SurfaceHello):
                continue
            hub.apply(message)
            dashboard.changed()
        dashboard.stop(note=_DAEMON_ENDED)

    await dashboard.run(alongside=[asyncio.create_task(listen())])
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return 0


async def daemon(*, debug: Path | None = None, screen: Screen | None = None) -> int:
    where: Screen = screen if screen is not None else Terminal()
    path = default_socket_path()
    if await alive(path):
        return await _as_peer(path=path, screen=where)
    journal = Journal(default_runs_root())
    await asyncio.to_thread(journal.prune, keep=_KEPT)
    hub = Hub(on_routed=_sink(debug), on_journal=journal.record)
    dashboard = Dashboard(casts=hub, screen=where)

    def heard(message: CastMessage) -> None:
        hub.apply(message)
        dashboard.changed()

    server = await serve(
        path=path,
        on_message=heard,
        on_attach=hub.attach_surface,
        on_detach=hub.detach_surface,
    )
    if debug is not None:
        dashboard.say(f"logging every event to {debug}")
    try:
        await dashboard.run()
    finally:
        await server.close()
    return 0


def init_command() -> Group:
    # Bare `vekna` is the daemon, which is why the group runs a body of its own
    # rather than printing help: the first one binds the socket and renders,
    # every one after attaches to it as another surface.
    @click.group(invoke_without_command=True)
    @click.option(
        "--debug",
        is_flag=True,
        help="Log every event the daemon processes to ~/.config/vekna/debug.log.",
    )
    def vekna(*, debug: bool = False) -> None:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            raise SystemExit(asyncio.run(daemon(debug=_DEBUG_LOG if debug else None)))

    vekna.add_command(_cast)
    vekna.add_command(_rituals)
    vekna.add_command(_casts)
    return vekna


def run() -> None:  # pragma: no cover
    init_command()()


if __name__ == "__main__":
    run()  # pragma: no cover
