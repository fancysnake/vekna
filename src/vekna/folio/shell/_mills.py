from vekna.lexicon import medium

from ._links import run_bash
from ._pacts import ShellResult


@medium
async def shell(command: str, *, cwd: str | None = None) -> ShellResult:
    stdout, stderr, exit_code = await run_bash(command, cwd=cwd)
    return ShellResult(stdout=stdout, stderr=stderr, exit_code=exit_code)
