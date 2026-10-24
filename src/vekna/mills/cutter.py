import asyncio
import signal
from collections.abc import Awaitable, Callable

from vekna.pacts.casts import Casts

_ID = 8
# Signal 0 is no signal: sending it asks whether the pid is there to send to.
_PROBE = 0
# Past the shell medium's own grace for reaping what it started, so a cast
# ending itself is not cut short of it.
GRACE_SECONDS = 10.0


# What a cancel the cast does not act on comes to. It is asked over the wire
# first; one that is still running a grace later — too old to read the ask, or
# stuck where a cancel never lands — is sent SIGINT, the Ctrl-C every cast
# obeys, and one that outlives that is killed. Only while its view still says
# it is running, so a pid the cast let go of is never signalled.
# shortcut: a pid reused inside the grace is signalled as the cast; a start
# time beside the pid would tell them apart.
class Cutter:
    def __init__(
        self,
        *,
        casts: Casts,
        pid_of: Callable[[str], Awaitable[int | None]],
        kill: Callable[[int, int], bool],
        say: Callable[[str], None],
        grace: float = GRACE_SECONDS,
    ) -> None:
        self._casts = casts
        self._pid_of = pid_of
        self._kill = kill
        self._say = say
        self._grace = grace

    async def cut(self, cast_id: str) -> None:
        if (view := self._casts.casts.get(cast_id)) is None:
            return
        pid = (
            view.hello.pid
            if view.hello.pid is not None
            else await self._pid_of(cast_id)
        )
        if pid is None:
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
        return view is not None and view.status == "running" and self._kill(pid, _PROBE)
