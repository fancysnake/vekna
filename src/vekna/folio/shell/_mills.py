from collections.abc import Callable

from vekna.lexicon import current_rite, current_rite_id, medium

from ._links import run_bash
from ._pacts import ShellResult


def _streamer() -> Callable[[str], None]:
    grimoire = current_rite().grimoire
    rite_id = current_rite_id()

    def emit(line: str) -> None:
        grimoire.rite_delta(rite_id, line)

    return emit


@medium
async def shell(
    command: str, *, cwd: str | None = None, stream: bool = True
) -> ShellResult:
    on_line = _streamer() if stream else None
    stdout, stderr, exit_code = await run_bash(command, cwd=cwd, on_line=on_line)
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
