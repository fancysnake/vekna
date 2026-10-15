import asyncio
from collections.abc import Callable

from vekna.pacts.casts import Casts, CastView
from vekna.pacts.circle import Exited, Limits, Spawn
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    CastQueued,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    WireMessage,
)


# The daemon's scheduler. A project runs as many casts at once as its
# `processes` says — every running cast of the project counts, whether the
# daemon spawned it or somebody typed `vekna cast` — and a queued one is spawned
# when a slot frees.
# ponytail: the queue lives in memory. Queued casts left behind by a daemon that
# stopped keep their `queued` records and are not picked up again; reading them
# back at start is the queue's (#141).
class Circle:
    def __init__(
        self,
        *,
        casts: Casts,
        apply: Callable[[CastMessage], None],
        spawn: Spawn,
        limits: Limits,
    ) -> None:
        self._casts = casts
        self._apply = apply
        self._spawn = spawn
        self._limits = limits
        self._queue: list[str] = []
        # Spawned and not yet exited. A cast between its spawn and its hello is
        # still `queued` in the view, and has to hold its slot all the same.
        self._launching: set[str] = set()
        self._tasks: set[asyncio.Task[None]] = set()

    def enqueue(self, hello: CastHello) -> None:
        self._apply(hello)
        self._apply(CastQueued(cast_id=hello.cast_id))
        self._queue.append(hello.cast_id)
        self._start()

    # A cast that ended freed its slot, so the queue gets another look.
    def ended(self) -> None:
        self._start()

    def _start(self) -> None:
        for cast_id in list(self._queue):
            view = self._casts.casts.get(cast_id)
            if view is None or view.status != "queued":
                self._queue.remove(cast_id)
            elif self._busy(view) < self._limits.processes(view.hello.project_root):
                self._queue.remove(cast_id)
                self._launch(view.hello)

    def _busy(self, queued: CastView) -> int:
        project = queued.hello.project
        return sum(
            1
            for cast_id, view in self._casts.casts.items()
            if view.hello.project == project
            and (view.status == "running" or cast_id in self._launching)
        )

    def _launch(self, hello: CastHello) -> None:
        self._launching.add(hello.cast_id)
        task = asyncio.create_task(self._run(hello))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # A cast still queued once its process has gone never said hello, so its
    # goodbye is the daemon's to write, with whatever the process last said.
    async def _run(self, hello: CastHello) -> None:
        exited = await self._spawn(hello)
        self._launching.discard(hello.cast_id)
        view = self._casts.casts.get(hello.cast_id)
        if view is not None and view.status == "queued":
            self._apply(
                CastGoodbye(cast_id=hello.cast_id, status="error", detail=_why(exited))
            )
        self._start()


# How many agent sessions run at once across every cast on the account, granted
# in the order asked.
class CodingPool:
    def __init__(
        self, *, tell: Callable[[str, WireMessage], bool], limits: Limits
    ) -> None:
        self._tell = tell
        self._limits = limits
        self._held: dict[str, str] = {}
        self._waiting: list[CodingSlotRequested] = []

    # However a cast ended, its slots go with it: one that died holding a slot
    # never said it was done.
    def ended(self, cast_id: str) -> None:
        self._held = {held: by for held, by in self._held.items() if by != cast_id}
        self._waiting = [ask for ask in self._waiting if ask.cast_id != cast_id]
        self._grant()

    def requested(self, request: CodingSlotRequested) -> None:
        self._waiting.append(request)
        self._grant()

    # Released before it was granted is a wait the cast gave up on.
    def released(self, release: CodingSlotReleased) -> None:
        self._held.pop(release.request_id, None)
        self._waiting = [
            ask for ask in self._waiting if ask.request_id != release.request_id
        ]
        self._grant()

    def _grant(self) -> None:
        limit = self._limits.coding()
        for ask in list(self._waiting):
            if limit is not None and len(self._held) >= limit:
                return
            self._waiting.remove(ask)
            self._held[ask.request_id] = ask.cast_id
            self._tell(
                ask.cast_id,
                CodingSlotGranted(cast_id=ask.cast_id, request_id=ask.request_id),
            )


def _why(exited: Exited) -> str:
    ended = "would not start" if exited.code is None else f"exited {exited.code}"
    return f"{ended} before its hello: {exited.said}" if exited.said else ended
