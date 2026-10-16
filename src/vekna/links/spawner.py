import asyncio
from collections.abc import Sequence
from pathlib import Path

from vekna.pacts.circle import Exited
from vekna.wire import CastHello, run_file

_LOG = "cast.log"
_RESUME = "--resume"
_LEASED = "--leased"


# A spawned cast is a `vekna cast --resume <id>` in the tree it was asked from,
# or in the pooled one leased for it, reading its own record, so nothing typed
# crosses the daemon. It has no terminal: what it prints goes to `cast.log`
# beside its record, which is where the reason a cast died before its hello is
# read back from.
class Spawner:
    def __init__(self, *, command: Sequence[str], runs: Path) -> None:
        self._command = command
        self._runs = runs

    async def __call__(self, hello: CastHello, tree: str | None) -> Exited:
        log = run_file(self._runs, hello.cast_id).parent / _LOG
        try:
            await asyncio.to_thread(log.parent.mkdir, parents=True, exist_ok=True)
            with log.open("ab") as out:
                process = await asyncio.create_subprocess_exec(
                    *self._command,
                    *([] if tree is None else [_LEASED]),
                    _RESUME,
                    hello.cast_id,
                    cwd=hello.project_root if tree is None else tree,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out,
                    stderr=asyncio.subprocess.STDOUT,
                )
                code = await process.wait()
        except OSError as error:
            return Exited(code=None, said=str(error))
        return Exited(code=code, said=await asyncio.to_thread(_last_line, log))


# A log that will not read back still leaves the exit code to say how it ended.
def _last_line(log: Path) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return str(error)
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""
