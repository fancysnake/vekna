import asyncio
from collections.abc import Sequence
from pathlib import Path

from vekna.pacts.circle import Exited
from vekna.wire import CastHello, run_file

_LOG = "cast.log"
_RESUME = "--resume"


# A spawned cast is a `vekna cast --resume <id>` in the tree it was asked for,
# reading its own record, so nothing typed crosses the daemon. It has no
# terminal: what it prints goes to `cast.log` beside its record, which is where
# the reason a cast died before its hello is read back from.
class Spawner:
    def __init__(self, *, command: Sequence[str], runs: Path) -> None:
        self._command = command
        self._runs = runs

    async def __call__(self, hello: CastHello) -> Exited:
        log = run_file(self._runs, hello.cast_id).parent / _LOG
        await asyncio.to_thread(log.parent.mkdir, parents=True, exist_ok=True)
        with log.open("ab") as out:
            try:
                process = await asyncio.create_subprocess_exec(
                    *self._command,
                    _RESUME,
                    hello.cast_id,
                    cwd=hello.project_root,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out,
                    stderr=asyncio.subprocess.STDOUT,
                )
            except OSError as error:
                return Exited(code=None, said=str(error))
            code = await process.wait()
        return Exited(code=code, said=await asyncio.to_thread(_last_line, log))


def _last_line(log: Path) -> str:
    lines = log.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return lines[-1] if lines else ""
