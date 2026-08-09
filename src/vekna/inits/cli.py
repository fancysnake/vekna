import asyncio
import contextlib
import importlib
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol, cast

import click
from click import Group

from vekna.gates.cli.dashboard import Dashboard
from vekna.gates.cli.screen import listing
from vekna.links.debug_log import DebugLog
from vekna.links.journal import Journal, default_runs_root
from vekna.links.socket_server import attach, default_socket_path, serve
from vekna.links.terminal import Terminal
from vekna.mills.debug import debug_line
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed
from vekna.pacts.screen import Screen
from vekna.wire import SurfaceHello, WireMessage, encode_frame, read_frames

_CAST_CONTEXT: dict[str, bool] = {"ignore_unknown_options": True}
_RUNTIME = "vekna.lexicon._inits"
_RECENT = 20
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


@click.command("casts", help="List the casts the daemon has seen, newest first.")
def _casts() -> None:
    records = Journal(default_runs_root()).recent(limit=_RECENT)
    click.echo(listing(records), nl=False)


_rituals.add_command(_rituals_list)
_rituals.add_command(_rituals_show)


def _sink(debug: Path | None) -> Callable[[Routed], None] | None:
    if debug is None:
        return None
    log = DebugLog(debug)

    def record(routed: Routed) -> None:
        log.write(debug_line(routed))

    return record


async def _live(
    dashboard: Dashboard, *, alongside: Sequence[asyncio.Task[None]] = ()
) -> None:
    tasks = [
        asyncio.create_task(dashboard.painting()),
        asyncio.create_task(dashboard.typing()),
        *alongside,
    ]
    try:
        await dashboard.wait()
    finally:
        for task in tasks:
            task.cancel()
        # Gathered rather than awaited one by one under `suppress`: the
        # cancellation comes back as a value instead of an exception raised into
        # this frame, which is both shorter and the only form `coverage` keeps
        # tracing through (see TODO.md).
        await asyncio.gather(*tasks, return_exceptions=True)


# A second `vekna` in the same account is a surface on the first: it says so, is
# replayed every live cast, and paints the same view. It journals nothing — the
# daemon that owns the socket owns the record.
async def _as_peer(*, path: Path, screen: Screen) -> int:
    reader, writer = await attach(path)
    writer.write(encode_frame(SurfaceHello()))
    hub = Hub()
    dashboard = Dashboard(casts=hub, screen=screen)
    dashboard.say(_PEER)

    async def listen() -> None:
        async for message in read_frames(reader):
            hub.apply(message)
            dashboard.changed()
        dashboard.stop(note=_DAEMON_ENDED)

    await _live(dashboard, alongside=[asyncio.create_task(listen())])
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return 0


async def daemon(*, debug: Path | None = None, screen: Screen | None = None) -> int:
    where: Screen = screen if screen is not None else Terminal()
    path = default_socket_path()
    hub = Hub(on_routed=_sink(debug), on_journal=Journal(default_runs_root()).record)
    dashboard = Dashboard(casts=hub, screen=where)

    def heard(message: WireMessage) -> None:
        hub.apply(message)
        dashboard.changed()

    server = await serve(
        path=path,
        on_message=heard,
        on_attach=hub.attach_surface,
        on_detach=hub.detach_surface,
    )
    if server is None:
        return await _as_peer(path=path, screen=where)
    if debug is not None:
        dashboard.say(f"logging every event to {debug}")
    try:
        await _live(dashboard)
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
