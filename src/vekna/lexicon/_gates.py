import asyncio
import contextlib
import importlib
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, cast

from pydantic import BaseModel

from ._dispatch import (
    component_flags,
    load_rituals_file,
    load_rituals_module,
    read_config,
)
from ._links import StandaloneRenderer, default_socket_path, probe_daemon
from ._mills import Compendium, Grimoire, run_cast
from ._pacts import FocusMissingError, Ritual, RitualError, Transition, done

_USAGE = (
    "usage: vekna cast <ritual> [--<component> value ...]\n"
    '       vekna cast --prompt "<text>"\n'
)
_HELP_FLAGS = frozenset({"-h", "--help"})
_PROMPT_FLAGS = frozenset({"-p", "--prompt"})
_PROMPT_NAME = "prompt"
_CODING_MODULE = "vekna.folio.coding"
_LOAD_ERRORS = (RitualError, ValueError, ImportError, OSError)
_OPTIONAL_FOLIOS = ("vekna.folio.coding_claude",)


def _load_optional_folios() -> None:
    for name in _OPTIONAL_FOLIOS:
        with contextlib.suppress(ModuleNotFoundError):
            importlib.import_module(name)


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
        lines.append("no rituals found (create a rituals.py in this directory)")
        return "\n".join(lines) + "\n"
    lines.append("available rituals:")
    lines += [
        f"  {name}{_component_options(compendium.ritual(name))}" for name in names
    ]
    return "\n".join(lines) + "\n"


# The lexicon may not import a folio, so the `coding` medium is reached
# dynamically — the same shim `inits` uses to reach the lexicon.
class _HasText(Protocol):
    @property
    def text(self) -> str: ...


class _NoComponents(BaseModel):
    pass


def _coding_medium() -> Callable[[str], Awaitable[object]]:
    module = importlib.import_module(_CODING_MODULE)
    return cast("Callable[[str], Awaitable[object]]", module.coding)


def _prompt_ritual(prompt: str) -> Ritual:
    coding = _coding_medium()

    async def ask(_: BaseModel) -> Transition:
        return done(cast("_HasText", await coding(prompt)).text)

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
        value = inline if separator else next(tokens, "")
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
    _load_optional_folios()
    try:
        the_ritual, components = _resolve_cast(argv)
    except _LOAD_ERRORS as error:
        sys.stderr.write(f"{error}\n")
        return 2
    await probe_daemon(socket_path=default_socket_path())
    renderer = StandaloneRenderer()
    grimoire = Grimoire(cast_id=the_ritual.name, on_event=renderer.render)
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
