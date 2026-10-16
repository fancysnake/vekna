import asyncio
import contextlib
import importlib
import itertools
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple
from uuid import uuid4

from pydantic import BaseModel, JsonValue, TypeAdapter

from vekna.wire import (
    NEEDS_TREE,
    CastHello,
    WireMessage,
    default_config_path,
    default_socket_path,
    parse_flags,
    project_config_path,
    project_of,
)

from ._links.daemon import DaemonLink, TeeChannel, ThrottledFocus, to_wire
from ._links.loader import load_rituals_module, load_rituals_source, read_config
from ._links.resume import read_run
from ._links.standalone import StandaloneRenderer
from ._links.unattended import UnattendedChannel
from ._mills.dispatch import component_flags
from ._mills.engine import (
    CODING_FOCUS,
    Compendium,
    Grimoire,
    current_rite,
    prompt_runner,
    run_cast,
)
from ._mills.graph import check_exits, step_graph
from ._mills.ledger import Ledger
from ._pacts import (
    Channel,
    Done,
    FocusMissingError,
    NoComponents,
    RiteEvent,
    Ritual,
    RitualDefinitionError,
    RitualError,
    RitualSource,
    StringOutput,
    Tome,
)

_USAGE = (
    "usage: vekna cast <ritual> [--<component> value ...]\n"
    '       vekna cast --prompt "<text>"\n'
    "       vekna cast --continue <cast_id>\n"
    "       vekna cast --unattended <ritual> ...  (refuse every decide)\n"
)
_RESUME_FLAG = "--resume"
_UNATTENDED_FLAG = "--unattended"
# Runtime-only, like `--resume`: the daemon spawns a cast with it, and a cast
# with it has no terminal to ask on.
_WIRED_FLAG = "--wired"
# Spawned in a tree the daemon leased for it.
_LEASED_FLAG = "--leased"
_LEADING_FLAGS = frozenset({_UNATTENDED_FLAG, _WIRED_FLAG, _LEASED_FLAG})
_NEEDS_TREE = "needs a worktree — the daemon queues it again for one\n"
_NO_RITUALS = (
    "no rituals found (create a rituals.py or a rituals/ package in this directory)"
)
_RITUALS_FILE = "rituals.py"
_RITUALS_PACKAGE = "rituals"
_HELP_FLAGS = frozenset({"-h", "--help"})
_PROMPT_FLAGS = frozenset({"-p", "--prompt"})
_PROMPT_NAME = "prompt"
_PROMPT_MEDIUM = "coding"
_LOAD_ERRORS = (RitualError, ValueError, ImportError, OSError)
# Validated rather than dumped: `model_dump()` hands back `dict[str, Any]`, and
# what the wire carries is JSON.
_COMPONENTS: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])
# The lexicon may not import a folio, so each one is loaded by name and asked
# to register what it offers.
_FOLIOS = ("vekna.folio.coding", "vekna.folio.coding_claude")


# Registration is an explicit call, not an import side effect: importing a
# folio twice must not mean registering twice, and tests need a seam that is
# not "delete the module from sys.modules".
def _load_folios() -> None:
    for name in _FOLIOS:
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(name).register()


# A directory counts only with an `__init__.py`, at every level: a `rituals/`
# holding anything else would otherwise shadow a parent's real rituals.py and
# offer nothing in its place.
def _is_package(directory: Path) -> bool:
    return (directory / "__init__.py").is_file()


class _Discovery(NamedTuple):
    source: Path | None
    # Walking past a `rituals/` that is not a package is right — one may sit
    # above a project that has its own source, and stopping there would shadow
    # it. Reporting "no rituals found (create a rituals.py or a rituals/
    # package)" while standing next to a directory called `rituals` is not: the
    # answer is one empty file, and nothing in that sentence says so. Only the
    # walk that came back empty has the right to say it, so it is recorded here
    # rather than re-derived by a second walk that could blame a directory a
    # loaded source has already answered for.
    near_miss: Path | None


# Not a precedence rule. Both spellings name the ritual source and neither says
# it is the one meant, so a half-finished move into rituals/ would keep casting
# the file it was moved out of — silently, which is the shape of bug this
# feature exists to remove.
def _find_rituals_source(start: Path) -> _Discovery:
    near_miss: Path | None = None
    for directory in (start, *start.parents):
        file = directory / _RITUALS_FILE
        package = directory / _RITUALS_PACKAGE
        found_file, found_package = file.is_file(), _is_package(package)
        if found_file and found_package:
            msg = (
                f"{file} and {package} both name the ritual source here"
                " — delete or rename one"
            )
            raise RitualDefinitionError(msg)
        if found_file:
            return _Discovery(file, None)
        if found_package:
            return _Discovery(package, None)
        if near_miss is None and package.is_dir():
            near_miss = package
    return _Discovery(None, near_miss)


def _no_rituals(near_miss: Path | None) -> str:
    if near_miss is None:
        return _NO_RITUALS
    return f"{_NO_RITUALS}\n({near_miss} is not one — every level needs an __init__.py)"


def _config_files(cwd: Path) -> list[Path]:
    found: list[Path] = []
    if (global_config := default_config_path()).is_file():
        found.append(global_config)
    if (project_config := project_config_path(cwd)) is not None:
        found.append(project_config)
    return found


class _Library(NamedTuple):
    compendium: Compendium
    # What an empty compendium should say. The walk that discovered nothing is
    # the only place that knows whether there was a near miss, and it has been
    # left behind by the time anyone asks.
    when_empty: str
    # Each configured module that did not import. Its warning is already on
    # stderr; what `list` still owes it is the exit code.
    skipped: tuple[str, ...]


# A module is somebody else's package: one that is not installed here must not
# take the project's own rituals down with it. Its sweep is all or nothing, so
# skipping it leaves nothing half-shelved.
def _load_tomes(
    tomes: Iterable[Tome], *, root: Path
) -> tuple[list[tuple[str, RitualSource]], list[str]]:
    shelves: list[tuple[str, RitualSource]] = []
    skipped: list[str] = []
    for namespace, module in tomes:
        try:
            found = load_rituals_module(module, root=root)
        except RitualDefinitionError as error:
            skipped.append(str(error))
            continue
        shelves.extend((namespace, source) for source in found)
    for message in skipped:
        sys.stderr.write(f"warning: {message} — its rituals are skipped\n")
    return shelves, skipped


# `files` is additive, not a replacement for the source found by walking up:
# naming that same file is how an author is explicit about it, so a source
# already loaded is skipped rather than colliding with itself. Two *different*
# sources claiming one ritual name is still an error.
# The loader reaches the filesystem and so may not touch the compendium in
# _mills: it hands back what it found, and binding the two is this layer's job.
def _build_library(cwd: Path) -> _Library:
    shelves: list[tuple[str, RitualSource]] = []
    seen_files: set[Path] = set()
    # Ordered as well as unique: a tome's namespace is its own, so loading them
    # after every file reorders nothing that can collide.
    tomes: dict[Tome, None] = {}

    def load_source(path: Path) -> None:
        # Resolved so `..`, symlinks and a config-relative spelling of the
        # discovered source all collapse to one entry — a package reached twice
        # deduplicates here exactly as a file does.
        if (resolved := path.resolve()) in seen_files:
            return
        seen_files.add(resolved)
        shelves.extend(("", found) for found in load_rituals_source(resolved))

    discovered = _find_rituals_source(cwd)
    if discovered.source is not None:
        load_source(discovered.source)
    for config in _config_files(cwd):
        rituals = read_config(config).rituals
        # Relative to the config file, not the cwd: a project .vekna.toml is
        # found by walking parents, and a global one is shared by every
        # directory — resolving against the cwd would mean a different file
        # each time.
        for relative in rituals.files:
            # The discovered source was found by looking, so it is there by
            # construction; a configured one is a line somebody typed, and the
            # bare `[Errno 2]` the loader would raise names the path it tried
            # without naming the file that asked for it.
            if not (named := config.parent / relative).exists():
                msg = f"{config}: [rituals] names {named}, which does not exist"
                raise RitualDefinitionError(msg)
            load_source(named)
        # Per name as well as module: a module the global config lists and a
        # project renames is reachable under both.
        tomes.update((tome, None) for tome in rituals.modules)
    from_tomes, skipped = _load_tomes(tomes, root=cwd)
    shelves.extend(from_tomes)
    # Every source loaded before any collision is reported, so one cast names
    # them all. A file that fails to import has already stopped the sweep:
    # against a half-loaded library the collisions would be invented.
    compendium = Compendium(shelves)
    # Every exit resolved before anything is cast: an annotation naming a class
    # no step takes is well-typed, so this check is the only thing that catches
    # it, and here it catches it on `list` and `show` as well as `cast`.
    for name in compendium.names():
        check_exits(compendium.ritual(name))
    # A near miss is only ever found when discovery came back empty, so
    # anything seen here was named by a config — and a config that loaded is
    # the answer to where the rituals were meant to come from.
    loaded = bool(seen_files or from_tomes)
    return _Library(
        compendium,
        _no_rituals(None if loaded else discovered.near_miss),
        tuple(skipped),
    )


def _component_options(ritual: Ritual) -> str:
    parts: list[str] = []
    for name, type_name, required in component_flags(ritual.components):
        flag = f"--{name.replace('_', '-')} <{type_name}>"
        parts.append(flag if required else f"[{flag}]")
    return "  " + " ".join(parts) if parts else ""


def _help_text(cwd: Path) -> str:
    lines = [
        _USAGE.rstrip(),
        "",
        (
            "Run a ritual defined in rituals.py or a rituals/ package"
            " (or configured via .vekna.toml)."
        ),
        "Each ritual's component fields are passed as --options.",
        "",
        '--prompt/-p "<text>" casts a one-step ritual on the coding medium',
        "instead, with no ritual source required.",
        "",
    ]
    try:
        library = _build_library(cwd)
    except _LOAD_ERRORS as error:
        lines.append(f"(could not load rituals: {error})")
        return "\n".join(lines) + "\n"
    compendium = library.compendium
    if not (names := compendium.names()):
        lines.append(library.when_empty)
        return "\n".join(lines) + "\n"
    lines.append("available rituals:")
    lines += [
        f"  {name}{_component_options(compendium.ritual(name))}" for name in names
    ]
    return "\n".join(lines) + "\n"


def _list_text(library: _Library) -> str:
    compendium = library.compendium
    if not (names := compendium.names()):
        return f"{library.when_empty}\n"
    return "".join(
        f"{name}{_component_options(compendium.ritual(name))}\n" for name in names
    )


def _component_lines(the_ritual: Ritual) -> list[str]:
    if not (flags := component_flags(the_ritual.components)):
        return ["  (none)"]
    return [
        f"  --{name.replace('_', '-')} <{type_name}>"
        + ("" if required else "  (optional)")
        for name, type_name, required in flags
    ]


def _show_text(the_ritual: Ritual) -> str:
    graph = step_graph(the_ritual)
    lines = [
        the_ritual.name,
        f"max steps: {the_ritual.max_steps}",
        *(["worktree: yes"] if the_ritual.worktree else []),
        "",
        "components:",
        *_component_lines(the_ritual),
        "",
        "steps:",
        *(f"  {label} → {', '.join(targets) or '?'}" for label, targets in graph),
    ]
    return "\n".join(lines) + "\n"


def _show(library: _Library, name: str) -> int:
    try:
        the_ritual = library.compendium.ritual(name)
    except RitualDefinitionError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(_show_text(the_ritual))
    return 0


def _library_or_usage() -> _Library | None:
    try:
        return _build_library(Path.cwd())
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return None


def rituals_list() -> int:
    if (library := _library_or_usage()) is None:
        return 2
    sys.stdout.write(_list_text(library))
    # The listing is all a check in CI has to go on, and a skipped module has
    # made it shorter without saying so on stdout.
    return 1 if library.skipped else 0


def rituals_show(name: str) -> int:
    if (library := _library_or_usage()) is None:
        return 2
    return _show(library, name)


def _prompt_ritual(prompt: str) -> Ritual:
    run_prompt = prompt_runner(_PROMPT_MEDIUM)

    async def ask(_: BaseModel) -> Done[StringOutput]:
        return Done(await run_prompt(prompt))

    return Ritual(
        name=_PROMPT_NAME,
        components=NoComponents,
        run=ask,
        max_steps=1,
        exits=(),
        ends=True,
    )


def _prompt_text(argv: list[str]) -> str | None:
    first, *rest = argv
    flag, separator, inline = first.partition("=")
    if flag not in _PROMPT_FLAGS:
        return None
    text = inline if separator else " ".join(rest)
    if separator and rest:
        raise ValueError(_USAGE.rstrip())
    if not text:
        raise ValueError(_USAGE.rstrip())
    return text


class _Plan(NamedTuple):
    ritual: Ritual
    components: BaseModel
    unattended: bool
    # What the interrupted cast already did, and which cast that was. Both None
    # for a cast that is starting rather than carrying one on.
    ledger: Ledger | None = None
    resumed_from: str | None = None
    # A queued record is the cast's first run, so it keeps the id the daemon
    # gave it rather than minting one that would leave the queued row open.
    cast_id: str | None = None
    # Spawned by the daemon: no terminal, so prompts are answered over the wire.
    wired: bool = False


# The record holds the components as the CLI already validated them once, so
# they are validated again against the same model rather than re-derived into
# flags and parsed back out.
def _resume(cast_id: str, *, unattended: bool) -> _Plan:
    resumption = read_run(cast_id)
    hello = resumption.record.hello
    the_ritual = _build_library(Path.cwd()).compendium.ritual(hello.ritual)
    components = the_ritual.components.model_validate(hello.components)
    if resumption.record.status == "queued":
        return _Plan(the_ritual, components, unattended, cast_id=cast_id)
    return _Plan(
        ritual=the_ritual,
        components=components,
        unattended=unattended,
        ledger=Ledger.from_resumption(resumption),
        resumed_from=cast_id,
    )


def _resolve_cast(argv: list[str], *, unattended: bool) -> _Plan:
    if (prompt := _prompt_text(argv)) is not None:
        return _Plan(_prompt_ritual(prompt), NoComponents(), unattended)
    name, *flags = argv
    # Both spellings, because `--prompt` takes both: `--resume=c1` otherwise
    # reached the compendium and came back as "no ritual named '--resume=c1'",
    # which names everything except what was actually wrong.
    flag, separator, inline = name.partition("=")
    if flag == _RESUME_FLAG:
        wanted = [inline] if separator else flags
        if not wanted or not wanted[0]:
            raise ValueError(_USAGE.rstrip())
        return _resume(wanted[0], unattended=unattended)
    the_ritual = _build_library(Path.cwd()).compendium.ritual(name)
    return _Plan(
        the_ritual, the_ritual.components.model_validate(parse_flags(flags)), unattended
    )


# A cast returns a model or nothing, so its result renders as JSON rather than
# as whatever repr the model happens to carry.
def _rendered(result: BaseModel | None) -> str:
    return "null" if result is None else result.model_dump_json()


async def _hello(*, cast_id: str, plan: _Plan) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root=str(Path.cwd()),
        project=await project_of(Path.cwd()),
        ritual=plan.ritual.name,
        components=_COMPONENTS.validate_json(plan.components.model_dump_json()),
        started_at=datetime.now(tz=UTC),
        resumed_from=plan.resumed_from,
        wired=plan.wired,
    )


# What a daemon arriving mid-cast has to be told: everything the grimoire has
# recorded, and any prompt already on screen, which is not in it.
def _backlog(
    *, cast_id: str, grimoire: Grimoire, channel: TeeChannel
) -> list[WireMessage]:
    replayed: list[WireMessage] = [
        to_wire(event, cast_id=cast_id) for event in grimoire.events
    ]
    return replayed + channel.open_prompts()


# Every agent session this cast opens counts against the daemon's coding limit.
# A cast with no coding focus is left to fail at the call that needs one, not
# refused here for work it may never do.
def _throttled(link: DaemonLink) -> contextlib.AbstractContextManager[None]:
    try:
        inner = CODING_FOCUS.resolve()
    except FocusMissingError:
        return contextlib.nullcontext()
    return CODING_FOCUS.scope(ThrottledFocus(inner=inner, link=link))


# Every way a cast can end goes through one notify: an `except` per error type
# would leave whatever it does not name — the AttributeError a step raises —
# silent, which is the walked-away-from-the-terminal case the notification
# exists for. `detail` outlives its block; `error` does not.
async def _cast(
    *,
    plan: _Plan,
    grimoire: Grimoire,
    channel: Channel,
    link: DaemonLink,
    renderer: StandaloneRenderer,
) -> int:
    try:
        with _throttled(link):
            result = await run_cast(
                ritual=plan.ritual,
                components=plan.components,
                grimoire=grimoire,
                channel=channel,
                ledger=plan.ledger,
            )
    except FocusMissingError as error:
        sys.stderr.write(f"{error}\n")
        code, detail = 2, str(error)
    except RitualError as error:
        sys.stderr.write(f"cast failed: {error}\n")
        code, detail = 1, str(error)
    except Exception as error:
        # A rituals.py under development dies here, and its traceback is the
        # whole diagnosis — say it to the desktop, then let it out unchanged.
        renderer.notify("failed", f"{plan.ritual.name}: {error}")
        raise
    else:
        await link.close(status="ok")
        renderer.notify("done", plan.ritual.name)
        sys.stdout.write(f"result: {_rendered(result)}\n")
        return 0
    await link.close(status="error", detail=detail)
    renderer.notify("failed", f"{plan.ritual.name}: {detail}")
    return code


# The renderer and the wire both, in that order: what the operator sees does not
# wait on a socket, and a cast with no daemon behaves exactly as it did.
async def _run(plan: _Plan) -> int:
    # Unique per cast, not per ritual, and a resumed cast is a new one: cast_id
    # is the wire's correlation key, and which cast this one carries on from is
    # a field of its own on the hello.
    cast_id = plan.cast_id if plan.cast_id is not None else uuid4().hex
    renderer = StandaloneRenderer()
    link = DaemonLink(
        socket_path=default_socket_path(),
        hello=await _hello(cast_id=cast_id, plan=plan),
    )
    tee = TeeChannel(
        inner=None if plan.wired else renderer,
        link=link,
        cast_id=cast_id,
        rite_id=lambda: current_rite().parent_id,
    )
    channel: Channel = UnattendedChannel() if plan.unattended else tee

    def emit(event: RiteEvent) -> None:
        renderer.render(event)
        link.send(to_wire(event, cast_id=cast_id))

    grimoire = Grimoire(cast_id=cast_id, on_event=emit)

    # The same backlog either way: at the start it is empty, and a daemon that
    # turns up later gets whatever has happened by then. One path, so the
    # mid-cast attach is not a road only a rare timing takes.
    def backlog() -> list[WireMessage]:
        return _backlog(cast_id=cast_id, grimoire=grimoire, channel=tee)

    await link.attach(backlog=backlog)
    watcher = asyncio.create_task(link.keep_attached(backlog))
    try:
        return await _cast(
            plan=plan, grimoire=grimoire, channel=channel, link=link, renderer=renderer
        )
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


# Only a queued first run asks: a cast typed by hand runs where it was typed, and
# a resumed one carries on in the tree its interrupted run left.
def _needs_tree(plan: _Plan, *, leased: bool) -> bool:
    return (
        plan.wired and plan.cast_id is not None and plan.ritual.worktree and not leased
    )


async def _drive(argv: list[str]) -> int:
    # Leading only, as the outer command hands them: past the ritual's name a
    # flag is a component's.
    leading = list(itertools.takewhile(_LEADING_FLAGS.__contains__, argv))
    argv = argv[len(leading) :]
    unattended = _UNATTENDED_FLAG in leading
    if argv and argv[0] in _HELP_FLAGS:
        sys.stdout.write(_help_text(Path.cwd()))
        return 0
    if not argv:
        sys.stderr.write(_USAGE)
        return 2
    _load_folios()
    try:
        plan = _resolve_cast(argv, unattended=unattended)._replace(
            wired=_WIRED_FLAG in leading
        )
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return 2
    if _needs_tree(plan, leased=_LEASED_FLAG in leading):
        sys.stderr.write(_NEEDS_TREE)
        return NEEDS_TREE
    return await _run(plan)


def main(argv: list[str]) -> int:
    return asyncio.run(_drive(argv))
