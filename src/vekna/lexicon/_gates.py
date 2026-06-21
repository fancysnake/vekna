import asyncio
import sys
from pathlib import Path

from ._dispatch import load_rituals
from ._links import StandaloneRenderer, default_socket_path, probe_daemon
from ._mills import Grimoire, run_cast
from ._pacts import RitualError

_USAGE = "usage: vekna cast <ritual> [--<component> value ...]\n"


def _find_rituals_file(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        candidate = directory / "rituals.py"
        if candidate.is_file():
            return candidate
    return None


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
    if not argv:
        sys.stderr.write(_USAGE)
        return 2
    name, *flags = argv
    if (rituals_file := _find_rituals_file(Path.cwd())) is None:
        sys.stderr.write("no rituals.py found (searched cwd and parents)\n")
        return 2
    try:
        the_ritual = load_rituals(rituals_file).ritual(name)
        components = the_ritual.components.model_validate(_parse_flags(flags))
    except (RitualError, ValueError) as error:
        sys.stderr.write(f"{error}\n")
        return 2
    await probe_daemon(socket_path=default_socket_path())
    grimoire = Grimoire(cast_id=name)
    result = await run_cast(ritual=the_ritual, components=components, grimoire=grimoire)
    renderer = StandaloneRenderer()
    for event in grimoire.events:
        await renderer.emit(event)
    sys.stdout.write(f"result: {result}\n")
    return 0


def main(argv: list[str]) -> int:
    return asyncio.run(_drive(argv))
