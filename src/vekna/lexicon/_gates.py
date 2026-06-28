import asyncio
import sys
from pathlib import Path

from ._dispatch import (
    component_flags,
    load_rituals_file,
    load_rituals_module,
    read_config,
)
from ._links import StandaloneRenderer, default_socket_path, probe_daemon
from ._mills import Compendium, Grimoire, run_cast
from ._pacts import Ritual, RitualError

_USAGE = "usage: vekna cast <ritual> [--<component> value ...]\n"
_HELP_FLAGS = frozenset({"-h", "--help"})
_LOAD_ERRORS = (RitualError, ValueError, ImportError, OSError)


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


def _build_compendium(cwd: Path) -> Compendium:
    compendium = Compendium()
    if (implicit := _find_rituals_file(cwd)) is not None:
        load_rituals_file(compendium, implicit)
    for config in _config_files(cwd):
        modules, files = read_config(config)
        for relative in files:
            load_rituals_file(compendium, cwd / relative)
        for module in modules:
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
    ]
    try:
        compendium = _build_compendium(cwd)
    except _LOAD_ERRORS as error:
        lines.append(f"(could not load rituals: {error})")
        return "\n".join(lines) + "\n"
    if not (names := compendium.names()):
        lines.append("no rituals found (create a rituals.py in this directory)")
        return "\n".join(lines) + "\n"
    lines.append("available rituals:")
    lines += [
        f"  {name}{_component_options(compendium.ritual(name))}" for name in names
    ]
    return "\n".join(lines) + "\n"


def _parse_flags(flags: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    tokens = iter(flags)
    for token in tokens:
        if not token.startswith("--"):
            msg = f"unexpected argument: {token!r}"
            raise ValueError(msg)
        key, separator, inline = token[2:].partition("=")
        value = inline if separator else next(tokens, "")
        parsed[key.replace("-", "_")] = value
    return parsed


async def _drive(argv: list[str]) -> int:
    if argv and argv[0] in _HELP_FLAGS:
        sys.stdout.write(_help_text(Path.cwd()))
        return 0
    if not argv:
        sys.stderr.write(_USAGE)
        return 2
    name, *flags = argv
    try:
        the_ritual = _build_compendium(Path.cwd()).ritual(name)
        components = the_ritual.components.model_validate(_parse_flags(flags))
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return 2
    await probe_daemon(socket_path=default_socket_path())
    grimoire = Grimoire(cast_id=name)
    renderer = StandaloneRenderer()
    result = await run_cast(
        ritual=the_ritual, components=components, grimoire=grimoire, channel=renderer
    )
    for event in grimoire.events:
        await renderer.emit(event)
    sys.stdout.write(f"result: {result}\n")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(_drive(argv))
