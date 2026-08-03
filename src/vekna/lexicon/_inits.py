import asyncio
import contextlib
import importlib
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from ._links.loader import (
    load_rituals_file,
    load_rituals_module,
    load_rituals_package,
    read_config,
)
from ._links.standalone import StandaloneRenderer, default_socket_path, probe_daemon
from ._mills.dispatch import component_flags
from ._mills.engine import Compendium, Grimoire, prompt_runner, run_cast
from ._mills.graph import step_graph
from ._pacts import (
    FocusMissingError,
    NoComponents,
    Ritual,
    RitualDefinitionError,
    RitualError,
    RitualSource,
    Transition,
    done,
)

_USAGE = (
    "usage: vekna cast <ritual> [--<component> value ...]\n"
    '       vekna cast --prompt "<text>"\n'
)
_NO_RITUALS = "no rituals found (create a rituals.py in this directory)"
_RITUALS_FILE = "rituals.py"
_RITUALS_PACKAGE = "rituals"
_HELP_FLAGS = frozenset({"-h", "--help"})
_PROMPT_FLAGS = frozenset({"-p", "--prompt"})
_PROMPT_NAME = "prompt"
_PROMPT_MEDIUM = "coding"
_LOAD_ERRORS = (RitualError, ValueError, ImportError, OSError)
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


# Not a precedence rule. Both spellings name the ritual source and neither says
# it is the one meant, so a half-finished move into rituals/ would keep casting
# the file it was moved out of — silently, which is the shape of bug this
# feature exists to remove.
def _find_rituals_source(start: Path) -> Path | None:
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
            return file
        if found_package:
            return package
    return None


def _config_files(cwd: Path) -> list[Path]:
    found: list[Path] = []
    global_config = Path.home() / ".config" / "vekna" / "config.toml"
    if global_config.is_file():
        found.append(global_config)
    for directory in (cwd, *cwd.parents):
        project_config = directory / ".vekna.toml"
        if project_config.is_file():
            found.append(project_config)
            break
    return found


# `files` is additive, not a replacement for the rituals.py found by walking up:
# naming that same file is how an author is explicit about it, so a source
# already loaded is skipped rather than colliding with itself. Two *different*
# sources claiming one ritual name is still an error.
# The loader reaches the filesystem and so may not touch the compendium in
# _mills: it hands back what it found, and binding the two is this layer's job.
def _register(*, compendium: Compendium, found: list[RitualSource]) -> None:
    for module in found:
        for the_ritual in module.rituals:
            compendium.register(the_ritual, source=module.source)
        for the_step in module.steps:
            compendium.register_step(the_step, source=module.source)


def _build_compendium(cwd: Path) -> Compendium:
    compendium = Compendium()
    seen_files: set[Path] = set()
    seen_modules: set[str] = set()

    def load_file(path: Path) -> None:
        # Resolved so `..`, symlinks and a config-relative spelling of the
        # discovered file all collapse to one entry.
        if (resolved := path.resolve()) not in seen_files:
            seen_files.add(resolved)
            _register(compendium=compendium, found=load_rituals_file(resolved))

    if (implicit := _find_rituals_source(cwd)) is not None:
        if implicit.is_dir():
            _register(
                compendium=compendium, found=load_rituals_package(implicit.resolve())
            )
        else:
            load_file(implicit)
    for config in _config_files(cwd):
        rituals = read_config(config).rituals
        # Relative to the config file, not the cwd: a project .vekna.toml is
        # found by walking parents, and a global one is shared by every
        # directory — resolving against the cwd would mean a different file
        # each time.
        for relative in rituals.files:
            load_file(config.parent / relative)
        for module in rituals.modules:
            if module not in seen_modules:
                seen_modules.add(module)
                _register(compendium=compendium, found=load_rituals_module(module))
    return compendium


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
        "Run a ritual defined in rituals.py (or configured via .vekna.toml).",
        "Each ritual's component fields are passed as --options.",
        "",
        '--prompt/-p "<text>" casts a one-step ritual on the coding medium',
        "instead, with no rituals.py required.",
        "",
    ]
    try:
        compendium = _build_compendium(cwd)
    except _LOAD_ERRORS as error:
        lines.append(f"(could not load rituals: {error})")
        return "\n".join(lines) + "\n"
    if not (names := compendium.names()):
        lines.append(_NO_RITUALS)
        return "\n".join(lines) + "\n"
    lines.append("available rituals:")
    lines += [
        f"  {name}{_component_options(compendium.ritual(name))}" for name in names
    ]
    return "\n".join(lines) + "\n"


def _list_text(compendium: Compendium) -> str:
    if not (names := compendium.names()):
        return f"{_NO_RITUALS}\n"
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


def _show_text(compendium: Compendium, the_ritual: Ritual) -> str:
    graph = step_graph(compendium, the_ritual)
    lines = [
        the_ritual.name,
        f"max steps: {the_ritual.max_steps}",
        "",
        "components:",
        *_component_lines(the_ritual),
        "",
        "steps:",
        *(f"  {label} → {', '.join(targets) or '?'}" for label, targets in graph),
    ]
    return "\n".join(lines) + "\n"


def _show(compendium: Compendium, name: str) -> int:
    try:
        the_ritual = compendium.ritual(name)
    except RitualDefinitionError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    sys.stdout.write(_show_text(compendium, the_ritual))
    return 0


def _compendium_or_usage() -> Compendium | None:
    try:
        return _build_compendium(Path.cwd())
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return None


def rituals_list() -> int:
    if (compendium := _compendium_or_usage()) is None:
        return 2
    sys.stdout.write(_list_text(compendium))
    return 0


def rituals_show(name: str) -> int:
    if (compendium := _compendium_or_usage()) is None:
        return 2
    return _show(compendium, name)


def _prompt_ritual(prompt: str) -> Ritual:
    run_prompt = prompt_runner(_PROMPT_MEDIUM)

    async def ask(_: BaseModel) -> Transition:
        return done(await run_prompt(prompt))

    return Ritual(name=_PROMPT_NAME, components=NoComponents, run=ask, max_steps=1)


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


def _parse_flags(flags: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    tokens = iter(flags)
    for token in tokens:
        if not token.startswith("--"):
            msg = f"unexpected argument: {token!r}"
            raise ValueError(msg)
        key, separator, inline = token[2:].partition("=")
        if separator:
            value = inline
        else:
            # Without this, `--a --b` reads --b as the value of --a and never
            # sets b at all. `None` is the sentinel because the tokens are
            # strings: a default of "" would read a trailing `--a` as `--a=`
            # and set the field to empty instead of naming the mistake.
            following = next(tokens, None)
            if following is None or following.startswith("--"):
                msg = f"--{key} is missing a value (write --{key}=<value>)"
                raise ValueError(msg)
            value = following
        parsed[key.replace("-", "_")] = value
    return parsed


def _resolve_cast(argv: list[str]) -> tuple[Ritual, BaseModel]:
    if (prompt := _prompt_text(argv)) is not None:
        return _prompt_ritual(prompt), NoComponents()
    name, *flags = argv
    the_ritual = _build_compendium(Path.cwd()).ritual(name)
    return the_ritual, the_ritual.components.model_validate(_parse_flags(flags))


# A cast returns a model or nothing, so its result renders as JSON rather than
# as whatever repr the model happens to carry.
def _rendered(result: BaseModel | None) -> str:
    return "null" if result is None else result.model_dump_json()


async def _drive(argv: list[str]) -> int:
    if argv and argv[0] in _HELP_FLAGS:
        sys.stdout.write(_help_text(Path.cwd()))
        return 0
    if not argv:
        sys.stderr.write(_USAGE)
        return 2
    _load_folios()
    try:
        the_ritual, components = _resolve_cast(argv)
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return 2
    # The answer is deliberately discarded until 0.6.0: the probe exists so the
    # attach path is already on the hot path, but nothing consumes a reachable
    # daemon yet. See docs/reborn/06-vekna-daemon.md.
    await probe_daemon(socket_path=default_socket_path())
    renderer = StandaloneRenderer()
    # Unique per cast, not per ritual: cast_id is the wire's correlation key
    # for deltas, decisions and locks, and CastHello carries the ritual name
    # in its own field.
    grimoire = Grimoire(cast_id=uuid4().hex, on_event=renderer.render)
    try:
        result = await run_cast(
            ritual=the_ritual,
            components=components,
            grimoire=grimoire,
            channel=renderer,
        )
    except FocusMissingError as error:
        sys.stderr.write(f"{error}\n")
        return 2
    except RitualError as error:
        sys.stderr.write(f"cast failed: {error}\n")
        return 1
    sys.stdout.write(f"result: {_rendered(result)}\n")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(_drive(argv))
