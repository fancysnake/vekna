import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path

from pydantic import TypeAdapter

from vekna.pacts.circle import Exited, Spawned
from vekna.wire import CastHello, run_file

_LOG = "cast.log"
_SPAWNED = "spawned.json"
_RESUME = "--resume"
_SPAWNED_ADAPTER: TypeAdapter[Spawned] = TypeAdapter(Spawned)


# A spawned cast is a `vekna cast --resume <id>` in the tree it was asked from,
# or in the pooled one leased for it, reading its own record, so nothing typed
# crosses the daemon. It has no terminal: what it prints goes to `cast.log`
# beside its record, which is where the reason a cast died before its hello is
# read back from. Beside them, `spawned.json` says the process is running for as
# long as this waits on it, so a daemon that stops under it leaves it behind.
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
                    _RESUME,
                    hello.cast_id,
                    cwd=hello.project_root if tree is None else tree,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=out,
                    stderr=asyncio.subprocess.STDOUT,
                )
            async with _marked(
                mark=log.with_name(_SPAWNED),
                spawned=Spawned(
                    cast_id=hello.cast_id,
                    pid=process.pid,
                    project=hello.project,
                    tree=tree,
                ),
                process=process,
            ):
                code = await process.wait()
        except OSError as error:
            return Exited(code=None, said=str(error))
        return Exited(code=code, said=await asyncio.to_thread(_last_line, log))

    # Read once, before the daemon spawns anything of its own. A mark whose
    # process is gone, or that will not read back, is cleared on the way.
    def left_behind(self) -> list[Spawned]:
        if not self._runs.is_dir():
            return []
        left: list[Spawned] = []
        for mark in self._runs.glob(f"*/{_SPAWNED}"):
            try:
                spawned = _SPAWNED_ADAPTER.validate_json(mark.read_bytes())
            except (OSError, ValueError):
                spawned = None
            if spawned is not None and pid_alive(spawned.pid):
                left.append(spawned)
            else:
                with contextlib.suppress(OSError):
                    mark.unlink(missing_ok=True)
        return left


# Removed only once the wait ends cleanly: a daemon cancelled mid-wait leaves
# the mark, and with it the cast, behind.
@contextlib.asynccontextmanager
async def _marked(
    *, mark: Path, spawned: Spawned, process: asyncio.subprocess.Process
) -> AsyncGenerator[None]:
    try:
        await asyncio.to_thread(mark.write_bytes, _SPAWNED_ADAPTER.dump_json(spawned))
    except OSError:
        # Unmarked, it is a cast the next daemon could lease a tree from under,
        # so it does not run at all.
        process.kill()
        await process.wait()
        raise
    waited = False
    try:
        yield
        waited = True
    finally:
        # A mark left behind only costs a look at a pid that is gone.
        if waited:
            with contextlib.suppress(OSError):
                await asyncio.to_thread(mark.unlink, missing_ok=True)


# Whether it was sent: a process already gone, or one not ours to signal, is
# not.
def signal_pid(pid: int, signum: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, signum)
    except OSError:
        return False
    return True


# shortcut: a pid reused by another process reads as the cast still running,
# holding its slot and tree until that process ends; a start time beside the
# pid would tell them apart.
def pid_alive(pid: int) -> bool:
    # Zero and below name a process group, not a process.
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


# A log that will not read back still leaves the exit code to say how it ended.
def _last_line(log: Path) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return str(error)
    lines = text.strip().splitlines()
    return lines[-1] if lines else ""
