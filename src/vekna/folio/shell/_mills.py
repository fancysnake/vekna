from collections.abc import Callable

from vekna.lexicon import RiteContext, current_rite, medium

from ._links import run_bash
from ._pacts import ShellResult


def _streamer(context: RiteContext) -> Callable[[str], None] | None:
    if (rite_id := context.parent_id) is None:
        return None

    def emit(line: str) -> None:
        context.grimoire.rite_delta(rite_id, line)

    return emit


@medium
async def shell(
    command: str, *, cwd: str | None = None, stream: bool = True
) -> ShellResult:
    on_line = _streamer(current_rite()) if stream else None
    stdout, stderr, exit_code = await run_bash(command, cwd=cwd, on_line=on_line)
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
