import asyncio
import contextlib
import importlib
import os
import sys
from pathlib import Path
from typing import Protocol, cast

import click
from click import Group

from vekna.gates.cli.dashboard import Dashboard
from vekna.gates.cli.screen import listing
from vekna.inits.daemon import CLI_MODULE, serve_daemon, stop_daemon, summon
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach
from vekna.links.terminal import Terminal
from vekna.mills.hub import Hub
from vekna.pacts.screen import Screen
from vekna.wire import (
    SurfaceHello,
    cast_frames,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
    project_of,
    read_frames,
)

# Docker's rule: what comes before the positional belongs to the outer command,
# what comes after belongs to what it runs. `allow_interspersed_args` off is
# what draws that line — without it a ritual's own `--continue` would be eaten
# here, and vekna's would be honoured wherever it happened to appear.
_CAST_CONTEXT: dict[str, bool] = {
    "ignore_unknown_options": True,
    "allow_interspersed_args": False,
}
_RUNTIME = "vekna.lexicon._inits"
_RESUME = "--resume"
_UNATTENDED = "--unattended"
_RECENT = 20
_DEBUG_LOG = "debug.log"
_DAEMON_ENDED = "the daemon ended"
_STARTED = "started the daemon — q leaves it running, `vekna stop` ends it"
_DEBUG_LATE = "--debug ignored: the daemon was already running (`vekna stop` first)"


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
@click.option(
    "--continue",
    "continued",
    metavar="CAST_ID",
    help="Carry an interrupted cast on from where it stopped.",
)
@click.option(
    "--unattended",
    is_flag=True,
    help="Refuse every decide: the cast is not watched, so a question is a hang.",
)
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(
    *,
    ritual_args: tuple[str, ...],
    continued: str | None = None,
    unattended: bool = False,
) -> None:
    if continued is not None:
        raise SystemExit(_continue(continued, unattended=unattended))
    flags = [_UNATTENDED] if unattended else []
    raise SystemExit(_runtime().main([*flags, *ritual_args]))


@click.command("list", help="List rituals and the options each one takes.")
def _rituals_list() -> None:
    raise SystemExit(_runtime().rituals_list())


@click.command("show", help="Show a ritual's components and step graph.")
@click.argument("name")
def _rituals_show(name: str) -> None:
    raise SystemExit(_runtime().rituals_show(name))


# `cats` is one transposition away from `cast`, and the fingers that type the
# verb all day will find it. Hidden: a reward for the slip, not a command.
_CATS = r"""
 /\_/\    /\_/\    /\_/\
( o.o )  ( -.- )  ( o.o )   MEOW :D
 > ^ <    > ^ <    > ^ <
"""


# The slip carries whatever `cast` was going to get — a ritual name, its
# options — so the same context as `cast` and everything after is eaten.
@click.command(
    "cats", context_settings=_CAST_CONTEXT, add_help_option=False, hidden=True
)
@click.argument("ignored", nargs=-1, type=click.UNPROCESSED)
def _cats(ignored: tuple[str, ...]) -> None:
    del ignored
    click.echo(_CATS)


@click.group("rituals", help="Inspect the ritual library.")
def _rituals() -> None:
    pass


async def _spawn_cast(cast_id: str, *, cwd: str, unattended: bool) -> int:
    flags = [_UNATTENDED] if unattended else []
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", CLI_MODULE, "cast", *flags, _RESUME, cast_id, cwd=cwd
    )
    return await process.wait()


# `log` rather than `casts`, which sat one letter from `cast` and did something
# else entirely: the verb an operator types all day is the one that must not
# have a near-homograph waiting for a slip of the finger.
@click.command("log", help="List the casts the daemon has seen, newest first.")
def _log() -> None:
    records = Journal(default_runs_root()).recent(limit=_RECENT)
    click.echo(listing(records), nl=False)


# Always a fresh process, in the directory the interrupted cast ran in: the
# ritual source is found by walking up from there, and a resume that ran here
# would cast a different project's ritual of the same name. The journal is
# handed over by name — the cast process reads it itself, being the only one
# that needs what is in it.
# The child is handed `_RESUME`, which is the runtime's own flag and skips this
# layer: reaching `--continue` again is how it would spawn itself forever.
def _continue(cast_id: str, *, unattended: bool) -> int:
    journal = Journal(default_runs_root())
    # What `vekna log` and the aborted row print is the id cut short, so what
    # comes back here is a prefix rather than the directory's own name.
    found = journal.matching(cast_id)
    if len(found) > 1:
        ambiguous = f"{cast_id!r} names {len(found)} casts — `vekna log` has the ids"
        raise click.ClickException(ambiguous)
    # A prefix that named nothing is read as itself, misses again, and is said
    # back in the sentence as the operator typed it.
    named = found[0] if found else cast_id
    if (record := journal.read(named)) is None:
        # A resolved prefix whose record will not read is the damaged row
        # `vekna log` is printing, and telling the operator the journal never
        # saw it is telling them about a line they are looking at.
        message = (
            f"cast {cast_id!r} is damaged — its record cannot be read, so there"
            " is nothing to resume it from"
            if found
            else f"no cast {cast_id!r} in the journal — `vekna log` has the ids"
        )
        raise click.ClickException(message)
    # The directory is the record's, not this shell's, and a project that has
    # been moved or deleted since is the likeliest thing to have gone wrong
    # between the two casts. Said as a sentence naming it, rather than as the
    # `NotADirectoryError` the spawn would otherwise raise from inside asyncio.
    root = record.hello.project_root
    if not Path(root).is_dir():
        message = f"{root} is not there any more — cast {cast_id!r} ran in it"
        raise click.ClickException(message)
    # The child is handed the whole id: it reads the journal by directory name,
    # and a prefix is this layer's convenience, not the runtime's.
    return asyncio.run(
        _spawn_cast(record.hello.cast_id, cwd=root, unattended=unattended)
    )


_rituals.add_command(_rituals_list)
_rituals.add_command(_rituals_show)


# Every `vekna` is a window on the daemon, summoning it when none is listening:
# it is replayed every live cast and paints the project it was opened in. It
# journals nothing — the daemon that owns the socket owns the record — and `q`
# leaves the daemon running.
async def window(*, debug: bool = False, screen: Screen | None = None) -> int:
    path = default_socket_path()
    hub = Hub()
    dashboard = Dashboard(
        casts=hub,
        screen=screen if screen is not None else Terminal(),
        project=await project_of(Path.cwd()),
    )
    if not await alive(path):
        await summon(path=path, debug=debug)
        dashboard.say(_STARTED)
    elif debug:
        dashboard.say(_DEBUG_LATE)
    reader, writer = await attach(path)
    writer.write(encode_frame(SurfaceHello()))

    # What a daemon sends a surface is what it heard from its casts, and nothing
    # that opens a connection is one of those.
    async def listen() -> None:
        async for message in cast_frames(read_frames(reader)):
            hub.apply(message)
            dashboard.changed()
        dashboard.stop(note=_DAEMON_ENDED)

    await dashboard.run(alongside=[asyncio.create_task(listen())])
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return 0


# Forked off and given a session of its own before the loop exists: the
# terminal that started it closing — and the hangup that comes with it — reaches
# the window and not the daemon, and the launcher's exit is what tells `vekna`
# the launch went through.
@click.command("serve", hidden=True, help="Start the daemon, detached, with no view.")
@click.option("--debug", is_flag=True, help="Log every event the daemon processes.")
def _serve(*, debug: bool = False) -> None:
    if os.fork():
        return
    os.setsid()
    # Resolved here rather than at import, so the environment a shell exports
    # is the one that decides where the log goes.
    where = default_state_root() / _DEBUG_LOG if debug else None
    raise SystemExit(asyncio.run(serve_daemon(debug=where)))


@click.command("stop", help="End the daemon. Running casts rejoin the next one.")
def _stop() -> None:
    click.echo(asyncio.run(stop_daemon()))


def init_command() -> Group:
    # Bare `vekna` is the project's view, which is why the group runs a body of
    # its own rather than printing help: the first one starts the daemon, and
    # every one attaches to it as a surface.
    @click.group(invoke_without_command=True)
    @click.option(
        "--debug",
        is_flag=True,
        help="Log every event the daemon processes to ~/.local/state/vekna/debug.log.",
    )
    def vekna(*, debug: bool = False) -> None:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            raise SystemExit(asyncio.run(window(debug=debug)))

    vekna.add_command(_cast)
    vekna.add_command(_rituals)
    vekna.add_command(_log)
    vekna.add_command(_cats)
    vekna.add_command(_serve)
    vekna.add_command(_stop)
    return vekna


def run() -> None:  # pragma: no cover
    init_command()()


if __name__ == "__main__":
    run()  # pragma: no cover
