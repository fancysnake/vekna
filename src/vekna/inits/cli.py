import asyncio
import contextlib
import importlib
import logging
import os
import sys
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import click
from click import Group

from vekna.gates.cli.commands import tended
from vekna.gates.cli.dashboard import Dashboard
from vekna.gates.cli.screen import listing, recorded
from vekna.gates.cli.tui import Opened, VeknaApp
from vekna.inits.daemon import CLI_MODULE, serve_daemon, stop_daemon, summon
from vekna.links.circle_config import MACHINE_KEYS, circle_problems
from vekna.links.journal import Journal
from vekna.links.socket_server import attach
from vekna.links.terminal import Terminal
from vekna.links.window_config import history_after, window_problems
from vekna.links.worktrees import branch_of
from vekna.mills.hub import Hub, replayed
from vekna.pacts.screen import Screen
from vekna.wire import (
    SHORT_ID,
    VERSION,
    AltarRequested,
    AltarTended,
    CastMessage,
    CastQueued,
    CastRefused,
    CastRequested,
    FailedTree,
    Opening,
    SurfaceHello,
    WireMessage,
    daemon_version,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
    parse_flags,
    project_of,
    read_frames,
    refused,
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
_NO_FOLLOW = "--no-follow"
_RECENT = 20
_QUEUE_USAGE = "--queue takes a ritual and its flags, and no other option"
_QUEUE_LOST = "the daemon went away before it queued the cast"
# How long the daemon gets to say the cast is queued.
_QUEUE_SECONDS = 5.0
_DEBUG_LOG = "debug.log"
_DAEMON_ENDED = "the daemon ended"
_VIEW_STOPPED = "the view stopped"
_STARTED = "started the daemon — it runs until `vekna stop`"
_DEBUG_LATE = "--debug ignored: the daemon was already running (`vekna stop` first)"
_NO_TREES = "no pooled worktrees for this project: run `vekna altar init`"
_NO_ANSWER = (
    "the daemon hung up without answering: it may predate this vekna"
    " (`vekna stop`, then retry)"
)


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
    @staticmethod
    def audit(problems: list[str], machine: Mapping[str, Collection[str]]) -> int: ...


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
@click.option(
    "--no-follow",
    "no_follow",
    is_flag=True,
    help="End with the cast's own steps rather than with the casts it queued.",
)
@click.option(
    "--queue",
    "queued",
    is_flag=True,
    help="Hand the cast to the daemon, which runs it once a slot is free.",
)
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(
    *,
    ritual_args: tuple[str, ...],
    continued: str | None = None,
    unattended: bool = False,
    no_follow: bool = False,
    queued: bool = False,
) -> None:
    if queued:
        if continued is not None or unattended or no_follow or not ritual_args:
            raise click.UsageError(_QUEUE_USAGE)
        raise SystemExit(asyncio.run(_queue(ritual_args)))
    flags = [
        *([_UNATTENDED] if unattended else []),
        *([_NO_FOLLOW] if no_follow else []),
    ]
    if continued is not None:
        raise SystemExit(_continue(continued, flags=flags))
    raise SystemExit(_runtime().main([*flags, *ritual_args]))


# The daemon spawns the cast with no terminal, so what it asks is answered in a
# window. Its flags are the ritual's to check: a bad one shows as that cast
# failing, as it does for a cast asked for with `c`.
async def _queue(ritual_args: tuple[str, ...]) -> int:
    ritual, *flags = ritual_args
    try:
        components = parse_flags(flags)
    except ValueError as error:
        raise click.UsageError(str(error)) from error
    cast_id = uuid4().hex
    request = CastRequested(
        project_root=str(Path.cwd()),
        ritual=ritual,
        components=components,
        cast_id=cast_id,
    )
    line = await _opened(opening=SurfaceHello(), debug=False)
    if line.note:
        click.echo(line.note, err=True)
    line.send(request)
    try:
        queued = await _said_queued(line.reader, cast_id)
    except TimeoutError:
        # A daemon that predates the id picks its own, and says nothing of ours.
        click.echo(f"asked for {ritual}")
        return 0
    finally:
        await line.close()
    if not queued:
        raise click.ClickException(_QUEUE_LOST)
    click.echo(f"queued {ritual} {cast_id[:SHORT_ID]}")
    return 0


# Whether the daemon said the cast is queued before it hung up, which may come
# as a reset connection instead of an ended one.
async def _said_queued(reader: asyncio.StreamReader, cast_id: str) -> bool:
    with contextlib.suppress(ConnectionError):
        async with asyncio.timeout(_QUEUE_SECONDS):
            async for message in read_frames(reader):
                if isinstance(message, CastRefused):
                    raise click.ClickException(message.reason)
                if isinstance(message, CastQueued) and message.cast_id == cast_id:
                    return True
    return False


@click.command("list", help="List rituals and the options each one takes.")
def _rituals_list() -> None:
    raise SystemExit(_runtime().rituals_list())


@click.command("show", help="Show a ritual's components and step graph.")
@click.argument("name")
def _rituals_show(name: str) -> None:
    raise SystemExit(_runtime().rituals_show(name))


# The cast runtime writes the report: most of what a config says is about
# rituals. `[circle]` and `[window]` are read on this side of the line, so
# their problems are handed over.
@click.command(
    "audit",
    help="Check the config that speaks for this directory: what is wrong, which"
    " file each setting is taken from, and what sets nothing.",
)
def _audit() -> None:
    cwd = Path.cwd()
    problems = [*circle_problems(cwd), *window_problems(cwd)]
    raise SystemExit(_runtime().audit(problems, {"circle": MACHINE_KEYS, "window": ()}))


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


async def _spawn_cast(cast_id: str, *, cwd: str, flags: list[str]) -> int:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", CLI_MODULE, "cast", *flags, _RESUME, cast_id, cwd=cwd
    )
    return await process.wait()


# `log` rather than `casts`, which sat one letter from `cast` and did something
# else entirely: the verb an operator types all day is the one that must not
# have a near-homograph waiting for a slip of the finger.
@click.command(
    "log",
    help="List the casts the daemon has seen, newest first. With a cast id,"
    " show that cast: its rites, why it ended, and what its failed rites wrote.",
)
@click.argument("cast_id", required=False)
def _log(cast_id: str | None) -> None:
    journal = Journal(default_runs_root())
    if cast_id is None:
        click.echo(listing(journal.recent(limit=_RECENT)), nl=False)
        return
    if (found := _resolved(journal, cast_id)) is None:
        message = f"cast {cast_id!r} is not in the journal — `vekna log` has the ids"
        raise click.ClickException(message)
    view, cut = replayed(found, journal.events(found))
    said = "" if cut is None else f"the log is unreadable past here — {cut}\n"
    if (record := journal.read(found)) is not None and record.gapped:
        said += "the daemon could not write part of this log — the cast ran on\n"
    if view is None:
        message = f"cast {cast_id!r} has no readable events {said}".rstrip()
        raise click.ClickException(message)
    click.echo(recorded(view) + said, nl=False)


# What `vekna log` and the aborted row print is the id cut short, so what comes
# back here is a prefix rather than the directory's own name: the one cast it
# names, or `None` for none. Several is not an id yet, and is said as such.
def _resolved(journal: Journal, cast_id: str) -> str | None:
    found = journal.matching(cast_id)
    if len(found) > 1:
        ambiguous = f"{cast_id!r} names {len(found)} casts — `vekna log` has the ids"
        raise click.ClickException(ambiguous)
    return found[0] if found else None


# Always a fresh process, in the directory the interrupted cast ran in: the
# ritual source is found by walking up from there, and a resume that ran here
# would cast a different project's ritual of the same name. The journal is
# handed over by name — the cast process reads it itself, being the only one
# that needs what is in it.
# The child is handed `_RESUME`, which is the runtime's own flag and skips this
# layer: reaching `--continue` again is how it would spawn itself forever.
def _continue(cast_id: str, *, flags: list[str]) -> int:
    journal = Journal(default_runs_root())
    found = _resolved(journal, cast_id)
    # A prefix that named nothing is read as itself, misses again, and is said
    # back in the sentence as the operator typed it.
    named = found or cast_id
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
    return asyncio.run(_spawn_cast(record.hello.cast_id, cwd=root, flags=flags))


_rituals.add_command(_rituals_list)
_rituals.add_command(_rituals_show)


# A line to the daemon, summoning it when none is listening, and what the
# command has to say about how it got one.
@dataclass(frozen=True, kw_only=True)
class _Line:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    note: str
    daemon: str

    def send(self, message: WireMessage) -> None:
        self.writer.write(encode_frame(message))

    async def close(self) -> None:
        self.writer.close()
        with contextlib.suppress(OSError):
            await self.writer.wait_closed()


async def _opened(*, opening: Opening, debug: bool) -> _Line:
    path = default_socket_path()
    note = _DEBUG_LATE if debug else ""
    try:
        daemon = await daemon_version(path)
    except OSError:
        await summon(path=path, debug=debug)
        note, daemon = _STARTED, VERSION
    if (refusal := refused(path, daemon)) is not None:
        raise click.ClickException(refusal)
    reader, writer = await attach(path)
    writer.write(encode_frame(opening))
    return _Line(reader=reader, writer=writer, note=note, daemon=daemon or VERSION)


# This vekna's version, and the daemon's only where it is another: within a
# major version the two may differ, and that is worth a glance.
def _versions(daemon: str) -> str:
    return f"vekna {VERSION}" + ("" if daemon == VERSION else f" · daemon {daemon}")


# What a daemon sends a surface is what it heard from its casts, and the
# refusal of a cast this window asked for. Returns once the daemon has gone.
async def _listen(
    line: _Line, *, hub: Hub, say: Callable[[str], None], changed: Callable[[], None]
) -> None:
    async for message in read_frames(line.reader):
        if isinstance(message, CastRefused):
            say(message.reason)
        elif isinstance(message, CastMessage):
            hub.apply(message)
            changed()


# Every `vekna` is a window on the daemon, summoning it when none is listening:
# it is replayed every live cast and paints the project it was opened in. It
# journals nothing — the daemon that owns the socket owns the record — and `q`
# leaves the daemon running.
async def window(*, debug: bool = False, screen: Screen | None = None) -> int:
    hub = Hub()
    line = await _opened(opening=SurfaceHello(), debug=debug)
    dashboard = Dashboard(
        casts=hub,
        screen=screen if screen is not None else Terminal(),
        project=await project_of(Path.cwd()),
        root=str(Path.cwd()),
        send=line.send,
    )
    if line.note:
        dashboard.say(line.note)

    async def listen() -> None:
        await _listen(line, hub=hub, say=dashboard.say, changed=dashboard.changed)
        dashboard.stop(note=_DAEMON_ENDED)

    await dashboard.run(alongside=[asyncio.create_task(listen())])
    await line.close()
    return 0


# The same window in Textual: the daemon's casts in a table, the one under the
# cursor beside it, prompts in a dialog. Its line to the daemon and its replay
# are the line view's; only the painting differs.
async def tui_window(*, debug: bool = False, headless: bool = False) -> int:
    hub = Hub()
    line = await _opened(opening=SurfaceHello(), debug=debug)
    after, ignored = history_after(Path.cwd())
    app = VeknaApp(
        casts=hub,
        opened=Opened(
            project=await project_of(Path.cwd()),
            root=str(Path.cwd()),
            history_after=after,
            title=_versions(line.daemon),
        ),
        send=line.send,
        branch_of=branch_of,
    )

    async def listen() -> None:
        await _listen(line, hub=hub, say=app.say, changed=app.changed)
        app.exit(message=_DAEMON_ENDED)

    # A listener that broke leaves a picture nothing will change again.
    def ended(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            app.exit(message=f"{_VIEW_STOPPED}: {error!r}")

    listening = asyncio.create_task(listen())
    listening.add_done_callback(ended)
    if note := " · ".join(said for said in (line.note, ignored) if said):
        app.call_later(app.say, note)
    try:
        await app.run_async(headless=headless)
    finally:
        listening.cancel()
        await asyncio.gather(listening, return_exceptions=True)
        await line.close()
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
    # To stderr, which is `daemon.log`.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Resolved here rather than at import, so the environment a shell exports
    # is the one that decides where the log goes.
    where = default_state_root() / _DEBUG_LOG if debug else None
    raise SystemExit(asyncio.run(serve_daemon(debug=where)))


@click.command("stop", help="End the daemon. Running casts rejoin the next one.")
def _stop() -> None:
    click.echo(asyncio.run(stop_daemon()))


# Not through `_opened`: asking what is running must neither start a daemon nor
# be refused by the one it is asking about.
@click.command("version", help="Show this vekna's version, and the running daemon's.")
def _version() -> None:
    click.echo(f"vekna {VERSION}")
    click.echo(asyncio.run(_daemon_line()))


async def _daemon_line() -> str:
    path = default_socket_path()
    try:
        daemon = await daemon_version(path)
    except OSError:
        return "daemon: not running"
    told = "version unknown, it predates `vekna version`" if daemon is None else daemon
    fit = "" if refused(path, daemon) is None else " — incompatible with this vekna"
    return f"daemon {told} on {path}{fit}"


# One tree of the pool by its number, the last part of its path.
_tree = click.argument("tree", type=click.IntRange(min=1), required=False)
_save = click.option(
    "--save",
    is_flag=True,
    help="First commit each tree's uncommitted work to a vekna/rescue/ branch.",
)


# Bare `vekna altar` names its subcommands, which is the group's own help.
@click.group(
    "altar",
    help=(
        "Tend this project's pooled worktrees: a ritual declared worktree=True"
        " runs only in a tree set up here."
    ),
)
def _altar() -> None:
    pass


@click.command("list", help="Show every pooled worktree and how it stands.")
def _altar_list() -> None:
    _tend(AltarRequested(project_root=str(Path.cwd())))


@click.command(
    "init",
    help=(
        "Make the worktrees the pool lacks and run `[circle] prepare` in each"
        " tree not set up yet."
    ),
)
def _altar_init() -> None:
    _tend(AltarRequested(project_root=str(Path.cwd()), init=True))


@click.command(
    "fix",
    help=(
        "Clean every worktree no cast holds, or only TREE, move it to the base"
        " branch and run `[circle] prepare` again. Uncommitted work is lost"
        " unless --save keeps it."
    ),
)
@_tree
@_save
def _altar_fix(*, tree: int | None = None, save: bool = False) -> None:
    _tend(AltarRequested(project_root=str(Path.cwd()), fix=True, save=save, tree=tree))


@click.command(
    "reset",
    help=(
        "Remove every worktree no cast holds, or only TREE, folder and all, then"
        " make it again as `init` does. Uncommitted work is lost unless --save"
        " keeps it."
    ),
)
@_tree
@_save
def _altar_reset(*, tree: int | None = None, save: bool = False) -> None:
    root = str(Path.cwd())
    _tend(
        AltarRequested(project_root=root, reset=True, init=True, save=save, tree=tree)
    )


_altar.add_command(_altar_list)
_altar.add_command(_altar_init)
_altar.add_command(_altar_fix)
_altar.add_command(_altar_reset)


def _tend(request: AltarRequested) -> None:
    reply = asyncio.run(_tended(request))
    for tree in reply.trees:
        click.echo(tended(tree))
    if not reply.trees:
        click.echo(_NO_TREES)
    if any(isinstance(tree, FailedTree) for tree in reply.trees):
        raise SystemExit(1)


# The daemon does the tending: only it knows which trees a cast holds. Its note
# goes to stderr: stdout is the trees.
async def _tended(request: AltarRequested) -> AltarTended:
    line = await _opened(opening=request, debug=False)
    if line.note:
        click.echo(line.note, err=True)
    try:
        reply = await anext(read_frames(line.reader), None)
    finally:
        await line.close()
    if isinstance(reply, AltarTended):
        return reply
    reason = reply.reason if isinstance(reply, CastRefused) else _NO_ANSWER
    raise click.ClickException(reason)


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
    @click.option(
        "--no-tui",
        "no_tui",
        is_flag=True,
        help="The line view: repainted whole, read a line at a time.",
    )
    def vekna(*, debug: bool = False, no_tui: bool = False) -> None:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            # Textual needs a terminal to draw on; anything else gets lines.
            drawn = not no_tui and os.isatty(0) and os.isatty(1)
            view = tui_window if drawn else window
            raise SystemExit(asyncio.run(view(debug=debug)))

    vekna.add_command(_cast)
    vekna.add_command(_rituals)
    vekna.add_command(_audit)
    vekna.add_command(_log)
    vekna.add_command(_cats)
    vekna.add_command(_serve)
    vekna.add_command(_stop)
    vekna.add_command(_altar)
    vekna.add_command(_version)
    return vekna


def run() -> None:  # pragma: no cover
    init_command()()


if __name__ == "__main__":
    run()  # pragma: no cover
