from vekna.lexicon import emit_delta, medium

from ._links import run_bash
from ._pacts import ShellResult


@medium
async def shell(
    command: str, *, cwd: str | None = None, stream: bool = True
) -> ShellResult:
    on_line = emit_delta if stream else None
    stdout, stderr, exit_code = await run_bash(command, cwd=cwd, on_line=on_line)
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
