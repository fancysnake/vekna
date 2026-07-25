import asyncio
import contextlib
import importlib
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from ._dispatch import component_flags
from ._graph import step_graph
from ._links import StandaloneRenderer, default_socket_path, probe_daemon
from ._loader import load_rituals_file, load_rituals_module, read_config
from ._mills import Compendium, Grimoire, prompt_runner, run_cast
from ._pacts import (
    FocusMissingError,
    Ritual,
    RitualDefinitionError,
    RitualError,
    Transition,
    done,
)

_USAGE = (
    "usage: vekna cast <ritual> [--<component> value ...]\n"
    '       vekna cast --prompt "<text>"\n'
)
_NO_RITUALS = "no rituals found (create a rituals.py in this directory)"
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


def _find_rituals_file(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "rituals.py"
        if candidate.is_file():
            return candidate
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
def _build_compendium(cwd: Path) -> Compendium:
    compendium = Compendium()
    seen_files: set[Path] = set()
    seen_modules: set[str] = set()

    def load_file(path: Path) -> None:
        # Resolved so `..`, symlinks and a config-relative spelling of the
        # discovered file all collapse to one entry.
        if (resolved := path.resolve()) not in seen_files:
            seen_files.add(resolved)
            load_rituals_file(compendium, resolved)

    if (implicit := _find_rituals_file(cwd)) is not None:
        load_file(implicit)
    for config in _config_files(cwd):
        modules, files = read_config(config)
        # Relative to the config file, not the cwd: a project .vekna.toml is
        # found by walking parents, and a global one is shared by every
        # directory — resolving against the cwd would mean a different file
        # each time.
        for relative in files:
            load_file(config.parent / relative)
        for module in modules:
            if module not in seen_modules:
                seen_modules.add(module)
                load_rituals_module(compendium, module)
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


class _NoComponents(BaseModel):
    pass


def _prompt_ritual(prompt: str) -> Ritual:
    run_prompt = prompt_runner(_PROMPT_MEDIUM)

    async def ask(_: BaseModel) -> Transition:
        return done(await run_prompt(prompt))

    return Ritual(name=_PROMPT_NAME, components=_NoComponents, run=ask, max_steps=1)


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
            # sets b at all.
            value = next(tokens, "")
            if value.startswith("--"):
                msg = f"--{key} is missing a value (write --{key}=<value>)"
                raise ValueError(msg)
        parsed[key.replace("-", "_")] = value
    return parsed


def _resolve_cast(argv: list[str]) -> tuple[Ritual, BaseModel]:
    if (prompt := _prompt_text(argv)) is not None:
        return _prompt_ritual(prompt), _NoComponents()
    name, *flags = argv
    the_ritual = _build_compendium(Path.cwd()).ritual(name)
    return the_ritual, the_ritual.components.model_validate(_parse_flags(flags))


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
    sys.stdout.write(f"result: {result}\n")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(_drive(argv))
