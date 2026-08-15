import asyncio
import itertools
from collections.abc import Sequence

from vekna.pacts.casts import Casts
from vekna.pacts.screen import Screen

from .screen import paint

# Long enough that a streaming rite does not repaint per line, short enough that
# the view reads as live.
_COALESCE_SECONDS = 0.1
_QUIT = frozenset({"q", "quit"})
_BACK = frozenset({"b", "back"})
_KEYS = "a number, b, or q"
_BROKE = "the view stopped"


# What the operator does with the view, and nothing about where the events came
# from: the daemon that owns the socket and a peer surface attached to it drive
# the same one, over the same two protocols.
class Dashboard:
    def __init__(self, *, casts: Casts, screen: Screen) -> None:
        self._casts = casts
        self._screen = screen
        self._focus: str | None = None
        self._note = ""
        self._changed = asyncio.Event()
        self._done = asyncio.Event()

    def changed(self) -> None:
        self._changed.set()

    def say(self, note: str) -> None:
        self._note = note
        self.changed()

    # Painted here rather than left to the loop: whatever ended the view is the
    # last thing worth saying about it, and the loop is about to be cancelled.
    def stop(self, *, note: str = "") -> None:
        self._note = note or self._note
        self._done.set()
        self._changed.set()
        self._show()

    @property
    def stopped(self) -> bool:
        return self._done.is_set()

    async def wait(self) -> None:
        await self._done.wait()

    # The view's own two coroutines and whatever the caller has to run beside
    # them — a peer's socket reader, say. Here rather than in the composition
    # root, which would otherwise have to know the assembly order to start a
    # dashboard at all.
    # A task that dies sets nothing, so every one of these is watched: a peer
    # whose reader hit a frame it could not decode would otherwise leave the
    # view sitting on a picture nobody will ever change again, with no way out
    # but a signal. Ending normally is not a failure — `typing` returns when
    # there is no stdin to read, and the daemon still has casts to serve.
    async def run(self, *, alongside: Sequence[asyncio.Task[None]] = ()) -> None:
        tasks = [
            asyncio.create_task(self.painting()),
            asyncio.create_task(self.typing()),
            *alongside,
        ]
        for task in tasks:
            task.add_done_callback(self._ended)
        try:
            await self.wait()
        finally:
            for task in tasks:
                task.cancel()
            # Gathered rather than awaited one by one under `suppress`: the
            # cancellation comes back as a value instead of an exception raised
            # into this frame, which is both shorter and the only form
            # `coverage` keeps tracing through (see TODO.md).
            await asyncio.gather(*tasks, return_exceptions=True)

    def _ended(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self.stop(note=f"{_BROKE}: {error!r}")

    async def painting(self) -> None:
        for _ in self._until_done():
            self._show()
            await self._changed.wait()
            self._changed.clear()
            # A burst of deltas is one repaint, not one each.
            await asyncio.sleep(_COALESCE_SECONDS)

    async def typing(self) -> None:
        for _ in self._until_done():
            if (line := await self._screen.read_line()) is None:
                # Nobody is typing: the view is still worth painting, and the
                # daemon still has casts to serve.
                return
            self._read(line)
            self.changed()

    # A `while` in disguise, and pylint's `while_used` is why: this repository
    # bans the statement, so the loop is spelled as the condition it is.
    def _until_done(self) -> "itertools.takewhile[int]":
        return itertools.takewhile(lambda _: not self._done.is_set(), itertools.count())

    def _read(self, line: str) -> None:
        lowered = line.lower()
        if lowered in _QUIT:
            self.stop()
        elif lowered in _BACK:
            self._focus = None
        elif lowered.isdecimal():
            self._focus = self._nth(int(lowered))
        elif lowered:
            self._note = f"{line!r} is not a cast — {_KEYS}"

    def _nth(self, index: int) -> str | None:
        found = list(self._casts.casts)
        if 1 <= index <= len(found):
            return found[index - 1]
        self._note = f"there is no cast {index}"
        return None

    # The note is shown once and then it has been said.
    def _show(self) -> None:
        self._screen.show(
            paint(
                casts=list(self._casts.casts.values()),
                focus=self._focus,
                note=self._note,
            )
        )
        self._note = ""
