import asyncio
import signal
from collections.abc import Callable

from vekna.pacts.casts import Casts

_ID = 8
# Past the shell medium's own grace for reaping what it started, so a cast
# ending itself is not cut short of it.
GRACE_SECONDS = 10.0


# What a cancel the cast does not act on comes to. It is asked over the wire
# first; one that is still running a grace later — stuck where a cancel never
# lands — is sent SIGINT, the Ctrl-C every cast obeys, and one that outlives
# that is killed. Only while its view still says it is running, so a pid the
# cast let go of is never signalled.
# shortcut: a pid reused inside the grace is signalled as the cast; a start
# time beside the pid would tell them apart.
class Cutter:
    def __init__(
        self,
        *,
        casts: Casts,
        alive: Callable[[int], bool],
        kill: Callable[[int, int], bool],
        say: Callable[[str], None],
        grace: float = GRACE_SECONDS,
    ) -> None:
        self._casts = casts
        self._alive = alive
        self._kill = kill
        self._say = say
        self._grace = grace
        self._cutting: dict[str, asyncio.Task[None]] = {}

    # One cut per cast however often it is asked for: a second SIGINT is what
    # turns a cast's graceful Ctrl-C into an abort.
    def cut(self, cast_id: str) -> asyncio.Task[None]:
        if (task := self._cutting.get(cast_id)) is None:
            task = self._cutting[cast_id] = asyncio.create_task(self._cut(cast_id))
            task.add_done_callback(lambda _: self._cutting.pop(cast_id, None))
        return task

    async def _cut(self, cast_id: str) -> None:
        if (view := self._casts.casts.get(cast_id)) is None:
            return
        if (pid := view.hello.pid) is None:
            self._say(
                f"cast {cast_id[:_ID]} has no pid to signal: stop it at its terminal"
            )
            return
        for signum in (signal.SIGINT, signal.SIGKILL):
            await asyncio.sleep(self._grace)
            if not self._running(cast_id, pid):
                return
            sent = self._kill(pid, signum)
            said = "sent" if sent else "could not send"
            self._say(
                f"cast {cast_id[:_ID]} still running: {said} {signum.name} to {pid}"
            )

    def _running(self, cast_id: str, pid: int) -> bool:
        view = self._casts.casts.get(cast_id)
        return view is not None and view.status == "running" and self._alive(pid)
