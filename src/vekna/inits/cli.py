import asyncio
import contextlib
import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, cast

import click
from click import Group

from vekna.gates.cli import lich as lich_screen
from vekna.gates.cli.dashboard import Dashboard
from vekna.gates.cli.screen import listing
from vekna.links.debug_log import DebugLog
from vekna.links.journal import Journal
from vekna.links.registry import LichRegistry
from vekna.links.socket_server import alive, attach, serve
from vekna.links.spawn import raise_detached
from vekna.links.terminal import Terminal
from vekna.mills.debug import debug_line
from vekna.mills.hub import Hub
from vekna.mills.liches import Liches, draw_name, sleeping_here
from vekna.pacts.lich import LichLine, Phylactery
from vekna.pacts.routing import Routed, Surface, Wiring
from vekna.pacts.screen import Screen
from vekna.wire import (
    CastMessage,
    LichDismissRequested,
    LichFell,
    LichRose,
    LichStatus,
    LichUpdate,
    SurfaceHello,
    SurfaceReady,
    default_runs_root,
    default_socket_path,
    default_state_root,
    encode_frame,
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
_DEBUG_LOG = "debug.log"
_DAEMON_ENDED = "the daemon ended"
_PEER = "attached to the vekna already running here"
_SERVE = "--serve"
_NO_DAEMON = "no vekna is running — start one with `vekna`, then raise the lich"
_NEW_ONE = "n"
# How long a one-shot surface waits for the daemon's picture of its liches. It
# is on the same machine and answers in a turn of its loop; this is the ceiling
# for a daemon wedged rather than a budget for a slow one.
_ANSWER_SECONDS = 5.0


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
@click.argument("ritual_args", nargs=-1, type=click.UNPROCESSED)
def _cast(ritual_args: tuple[str, ...], continued: str | None = None) -> None:
    if continued is not None:
        raise SystemExit(_continue(continued))
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
def _continue(cast_id: str) -> int:
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
        message = f"no cast {cast_id!r} in the journal — `vekna log` has the ids"
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
    return asyncio.run(_spawn_cast(record.hello.cast_id, cwd=root))


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

    # What a daemon sends a surface is what it heard from its casts, plus what
    # it knows about its liches — which this view has no column for yet, so it
    # is read past rather than applied.
    async def listen() -> None:
        async for message in read_frames(reader):
            if not isinstance(message, CastMessage):
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
    routed = _sink(debug)
    hub = Hub(on_routed=routed, on_journal=journal.record)
    liches = Liches(registry=LichRegistry(default_state_root()), on_routed=routed)
    dashboard = Dashboard(casts=hub, screen=where)

    def heard(message: CastMessage) -> None:
        hub.apply(message)
        dashboard.changed()

    # The cast replay first, then the liches, then the word that the picture is
    # complete — which is what lets `vekna liches` ask a question and leave
    # rather than wait out a timeout.
    def attached(surface: Surface) -> None:
        hub.attach_surface(surface)
        for view in liches.live.values():
            surface.send(view.rose)
            if view.said is not None:
                surface.send(view.said)
        surface.send(SurfaceReady())

    def rose(message: LichRose, station: Surface) -> str | None:
        refused = liches.rose(message, station)
        dashboard.changed()
        return refused

    def lich_said(message: LichUpdate) -> None:
        liches.apply(message)
        dashboard.changed()

    server = await serve(
        path=path,
        wiring=Wiring(
            on_message=heard,
            on_attach=attached,
            on_detach=hub.detach_surface,
            on_rise=rose,
            on_lich=lich_said,
            on_fallen=liches.gone,
            on_command=liches.command,
        ),
    )
    if debug is not None:
        dashboard.say(f"logging every event to {debug}")
    try:
        await dashboard.run()
    finally:
        await server.close()
    return 0


# A one-shot surface: attach, take the daemon's picture of its liches, leave.
# Liveness is only ever this — a socket the daemon is holding — so a command
# that wants it has to ask, and nothing on disk is allowed to claim it.
async def _live_liches(path: Path) -> dict[str, LichStatus | None]:
    reader, writer = await attach(path)
    writer.write(encode_frame(SurfaceHello()))
    live: dict[str, LichStatus | None] = {}

    async def read_until_ready() -> None:
        async for message in read_frames(reader):
            if isinstance(message, LichRose):
                live.setdefault(message.name, None)
            elif isinstance(message, LichStatus):
                live[message.name] = message
            elif isinstance(message, SurfaceReady):
                return

    try:
        await asyncio.wait_for(read_until_ready(), timeout=_ANSWER_SECONDS)
    except TimeoutError as timed_out:
        message = "the vekna daemon did not answer — is it wedged?"
        raise click.ClickException(message) from timed_out
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return live


# One line per lich: its row, whether the daemon can reach it, and what it last
# cast — that last read out of the journal, because a lich's history is a query
# over `runs/` and not something the registry keeps a second copy of.
def _lines(
    rows: list[Phylactery], *, live: dict[str, LichStatus | None]
) -> list[LichLine]:
    journal = Journal(default_runs_root())
    return [
        LichLine(
            row=row,
            live=row.name in live,
            said=live.get(row.name),
            last=None if row.last_cast is None else journal.read(row.last_cast),
        )
        for row in rows
    ]


async def list_liches() -> int:
    path = default_socket_path()
    live = await _live_liches(path) if await alive(path) else {}
    rows = LichRegistry(default_state_root()).rows()
    click.echo(lich_screen.listing(_lines(rows, live=live)), nl=False)
    return 0


# The lich process. It loads no ritual code and never will: it dials the daemon,
# says what it is, and waits to be told something — which is what keeps it
# inside the daemon's import rule, so a broken `rituals.py` still kills only the
# cast process that loaded it.
# The loop ends when the daemon does. A lich with no daemon has no routing, no
# registry and no journal, so there is nothing for it to go on being.
# ponytail: no reconnect. A daemon restarted under a lich leaves the row and
# loses the process; raising it again revives it. A retry loop is the upgrade.
async def serve_lich(*, name: str, root: str) -> int:
    reader, writer = await attach(default_socket_path())
    writer.write(encode_frame(LichRose(name=name, root=root, pid=os.getpid())))
    writer.write(encode_frame(LichStatus(name=name)))
    async for message in read_frames(reader):
        if isinstance(message, LichDismissRequested) and message.name == name:
            writer.write(encode_frame(LichFell(name=name, reason="dismissed")))
            break
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return 0


async def _spawn_lich(*, name: str, root: str) -> None:
    await raise_detached(
        argv=[sys.executable, "-m", _CLI_MODULE, "lich", _SERVE, name, root], cwd=root
    )


# Which lich `vekna lich` means. The task is the flags' when they are given; it
# is the only sleeper here when there is one and nothing to ask about; and it is
# a question otherwise, because guessing is wrong in both directions — reviving
# one you had finished with is no better than abandoning one you meant to carry
# on.
async def _chosen(sleeping: list[LichLine], *, screen: Screen) -> str | None:
    if not sleeping:
        return None
    screen.show(lich_screen.raising_prompt(sleeping))
    # No answer at all — a closed stdin, or Enter — is the answer the prompt
    # already offers as its last line: a new one. Nothing is revived by
    # accident, which is the half of this that cannot be taken back.
    answer = (await screen.read_line() or _NEW_ONE).strip() or _NEW_ONE
    if answer == _NEW_ONE:
        return None
    if answer.isdecimal() and 1 <= int(answer) <= len(sleeping):
        return sleeping[int(answer) - 1].row.name
    if answer in {line.row.name for line in sleeping}:
        return answer
    message = f"{answer!r} is not one of those — nothing was raised"
    raise click.ClickException(message)


async def raise_lich(
    *, named: str | None, fresh: bool, screen: Screen | None = None
) -> int:
    path = default_socket_path()
    if not await alive(path):
        raise click.ClickException(_NO_DAEMON)
    live = await _live_liches(path)
    rows = LichRegistry(default_state_root()).rows()
    here = str(Path.cwd())
    # A name that is live is not raised again: two processes answering to one
    # address is the one thing the daemon cannot sort out, and it is a slip to
    # be named rather than a race to be lost.
    if named is not None and named in live:
        message = f"{named} is already standing — `vekna lich attach {named}`"
        raise click.ClickException(message)
    name = named or await _drawn_or_chosen(
        fresh=fresh,
        taken={row.name for row in rows} | set(live),
        # Dormant, and rooted here: a lich the daemon can already reach is not
        # something to raise, and one rooted elsewhere is not something this
        # directory can carry on.
        sleeping=[
            line
            for line in _lines(sleeping_here(rows, root=here), live=live)
            if not line.live
        ],
        screen=screen if screen is not None else Terminal(),
    )
    # A revived lich stands in its own root, not in whatever directory the
    # command was typed in — that is what the row remembers it for. A project
    # moved or deleted since is the likeliest thing to have gone wrong in
    # between, and it is said as a sentence rather than as the `chdir` failure
    # the spawn would otherwise raise from inside asyncio.
    root = next((row.root for row in rows if row.name == name), here)
    if not await asyncio.to_thread(Path(root).is_dir):
        message = f"{root} is not there any more — {name} stood in it"
        raise click.ClickException(message)
    await _spawn_lich(name=name, root=root)
    click.echo(f"{name} stands in {root}")
    return 0


async def _drawn_or_chosen(
    *, fresh: bool, taken: set[str], sleeping: list[LichLine], screen: Screen
) -> str:
    if fresh:
        return draw_name(taken=taken)
    return await _chosen(sleeping, screen=screen) or draw_name(taken=taken)


# The row goes whether or not a process is holding it: a dormant lich is a row
# and nothing else, so dropping it is the whole of dismissing one.
async def dismiss_lich(name: str) -> int:
    path = default_socket_path()
    if not await alive(path):
        raise click.ClickException(_NO_DAEMON)
    known = {row.name for row in LichRegistry(default_state_root()).rows()}
    if name not in known | set(await _live_liches(path)):
        message = f"no lich named {name!r} — `vekna liches` has them"
        raise click.ClickException(message)
    _, writer = await attach(path)
    writer.write(encode_frame(SurfaceHello()))
    writer.write(encode_frame(LichDismissRequested(name=name)))
    # Closing after the drain does not discard what is buffered: the daemon
    # reads the frame and *then* the end of the connection, so there is no
    # acknowledgement to wait for and nothing to race.
    with contextlib.suppress(OSError):
        await writer.drain()
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    click.echo(f"{name} is dismissed")
    return 0


def init_command() -> Group:
    # Bare `vekna` is the daemon, which is why the group runs a body of its own
    # rather than printing help: the first one binds the socket and renders,
    # every one after attaches to it as another surface.
    @click.group(invoke_without_command=True)
    @click.option(
        "--debug",
        is_flag=True,
        help="Log every event the daemon processes to ~/.local/state/vekna/debug.log.",
    )
    def vekna(*, debug: bool = False) -> None:
        ctx = click.get_current_context()
        if ctx.invoked_subcommand is None:
            # Resolved here rather than at import, so the environment a shell
            # exports is the one that decides where the log goes.
            where = default_state_root() / _DEBUG_LOG if debug else None
            raise SystemExit(asyncio.run(daemon(debug=where)))

    vekna.add_command(_cast)
    vekna.add_command(_rituals)
    vekna.add_command(_log)
    vekna.add_command(_lich_command())
    vekna.add_command(_liches_command())
    return vekna


# `lich` is a group that also does something on its own, for the reason bare
# `vekna` is: raising one is the common case and `vekna lich raise` would be a
# word typed for nothing.
def _lich_command() -> Group:
    @click.group("lich", invoke_without_command=True, help="Raise a lich here.")
    @click.option("--name", help="Raise this one, dormant or new, in its own root.")
    @click.option("--new", "fresh", is_flag=True, help="Always raise a fresh one.")
    # How the detached process is told what it is. Hidden because nobody types
    # it: `vekna lich` spawns it, and a person running it by hand would be
    # standing a lich in the foreground of their shell by accident.
    @click.option("--serve", "serving", nargs=2, hidden=True)
    def lich(*, name: str | None, fresh: bool, serving: tuple[str, str] | None) -> None:
        if click.get_current_context().invoked_subcommand is not None:
            return
        if serving:
            raise SystemExit(asyncio.run(serve_lich(name=serving[0], root=serving[1])))
        raise SystemExit(asyncio.run(raise_lich(named=name, fresh=fresh)))

    lich.add_command(_dismiss_command)
    return lich


@click.command("dismiss", help="End a lich for good and drop its row.")
@click.argument("name")
def _dismiss_command(name: str) -> None:
    raise SystemExit(asyncio.run(dismiss_lich(name)))


def _liches_command() -> click.Command:
    @click.command("liches", help="List the liches this account has, live or not.")
    def liches() -> None:
        raise SystemExit(asyncio.run(list_liches()))

    return liches


def run() -> None:  # pragma: no cover
    init_command()()


if __name__ == "__main__":
    run()  # pragma: no cover
