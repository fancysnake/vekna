import asyncio
import contextlib
import itertools
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from vekna.pacts.casts import Casts, CastView
from vekna.pacts.screen import Screen
from vekna.wire import WireMessage

from .commands import request_cast, send_answer
from .screen import ordered, paint, scoped

# Long enough that a streaming rite does not repaint per line, short enough that
# the view reads as live.
_COALESCE_SECONDS = 0.1
# How often a view with nothing happening in it repaints anyway, which is what
# makes the elapsed columns a clock rather than a timestamp.
_TICK_SECONDS = 1.0
_QUIT = frozenset({"q", "quit"})
_BACK = frozenset({"b", "back"})
_EVERY = frozenset({"g", "global"})
_HOME = frozenset({"p", "project"})
_KEYS = "a number, c <ritual>, a <answer>, b, g, p, or q"
_CAST = "c "
_ANSWER = "a "
_BROKE = "the view stopped"


# Where this view opened — its project, and the directory a ritual started from
# it runs in — and what it is showing: every project instead, and the one cast
# drilled into. One attribute on the view rather than four.
@dataclass
class _Scope:
    home: str
    root: str
    every: bool = False
    focus: str | None = None

    @property
    def project(self) -> str | None:
        return None if self.every else self.home


# What the operator does with the view, and nothing about where the events came
# from: it reads casts and paints a screen, each through a protocol.
class Dashboard:
    # `send` is the window's line to the daemon, and `root` the directory it was
    # opened in, which is where a ritual it starts runs.
    def __init__(
        self,
        *,
        casts: Casts,
        screen: Screen,
        project: str,
        root: str,
        send: Callable[[WireMessage], None],
    ) -> None:
        self._casts = casts
        self._screen = screen
        self._send = send
        self._scope = _Scope(home=project, root=root)
        self._note = ""
        self._changed = asyncio.Event()
        self._done = asyncio.Event()

    def changed(self) -> None:
        self._changed.set()

    # Joined onto whatever has not been painted yet: two things said before the
    # first frame are both worth hearing, and the caller should not have to know
    # which of them the view would otherwise drop.
    def say(self, note: str) -> None:
        self._note = f"{self._note} · {note}" if self._note else note
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

    # The elapsed columns move whether or not a cast has anything to say, so the
    # wait is bounded: a view of casts that are all thinking still counts up.
    async def painting(self) -> None:
        for _ in self._until_done():
            self._show()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout=_TICK_SECONDS)
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
            self._scope.focus = None
        elif lowered in _EVERY:
            self._scope.every, self._scope.focus = True, None
        elif lowered in _HOME:
            self._scope.every, self._scope.focus = False, None
        elif lowered.startswith(_CAST):
            self._note = request_cast(
                typed=line[len(_CAST) :], root=self._scope.root, send=self._send
            )
        elif lowered.startswith(_ANSWER):
            self._answer(line[len(_ANSWER) :].strip())
        elif lowered.isdecimal():
            self._scope.focus = self._nth(int(lowered))
        elif lowered:
            self._note = f"{line!r} is not a cast — {_KEYS}"

    # The oldest open prompt of the cast in view.
    def _answer(self, typed: str) -> None:
        view = (
            None
            if self._scope.focus is None
            else self._casts.casts.get(self._scope.focus)
        )
        if view is None or not view.waiting:
            self._note = "nothing to answer — open a waiting cast first"
            return
        request = next(iter(view.waiting.values())).request
        if (
            refused := send_answer(request=request, typed=typed, send=self._send)
        ) is not None:
            self._note = refused

    # Worked out once for both the listing and the number typed against it, or
    # the number picks the cast above the one it is next to.
    def _listed(self) -> list[CastView]:
        return ordered(scoped(list(self._casts.casts.values()), self._scope.project))

    def _nth(self, index: int) -> str | None:
        found = self._listed()
        if 1 <= index <= len(found):
            return found[index - 1].hello.cast_id
        self._note = f"there is no cast {index}"
        return None

    # The note is shown once and then it has been said.
    def _show(self) -> None:
        self._screen.show(
            paint(
                listed=self._listed(),
                focus=self._scope.focus,
                project=self._scope.project,
                note=self._note,
            )
        )
        self._note = ""
