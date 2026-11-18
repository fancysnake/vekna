import asyncio
import contextlib
import itertools
import shutil
from collections.abc import AsyncGenerator, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from typing_extensions import override

from vekna.lexicon._pacts import (
    Channel,
    Display,
    EndStatus,
    RiteBegan,
    RiteEnded,
    RiteEvent,
)

from .picture import KEYS, Entry, Log, Picture, frame, summary, whole_log
from .standalone import Revisable, StandaloneRenderer, question_height

_ALTERNATE = "\x1b[?1049h"
_PLAIN = "\x1b[?1049l"
# Long enough that a streaming rite does not repaint per line, short enough that
# the board reads as live.
_COALESCE_SECONDS = 0.1
# How often a board with nothing happening on it repaints anyway, which is what
# makes the elapsed column a clock.
_TICK_SECONDS = 1.0
_MAX_DIGITS = 4
_LOG = "l"
_BACK = "— Enter returns to the board —"
_BROKE = "the board stopped"


# What the typed cast writes to: its terminal, until the board takes the screen
# and its lines go to its place on the board instead.
class Diverted(Revisable):
    def __init__(self, screen: Revisable) -> None:
        self.log = Log()
        self._screen = screen
        self._to: Revisable = screen

    def divert(self) -> None:
        self._to = self.log

    def restore(self) -> None:
        self._to = self._screen

    # An OSC sequence paints nothing — it is a desktop notification — so it is
    # the terminal's to hear wherever the lines are going.
    @override
    def write(self, text: str, /) -> int:
        if text.startswith("\x1b]"):
            return self._screen.write(text)
        return self._to.write(text)

    @override
    def flush(self) -> None:
        self._screen.flush()

    @override
    def isatty(self) -> bool:
        return self._screen.isatty()

    @property
    @override
    def mark(self) -> int:
        return self._to.mark

    @override
    def overwrite(self, mark: int, text: str) -> bool:
        return self._to.overwrite(mark, text)


# closed: the plain terminal. pending: a cast arrived while a question was on
# it, and the board opens after the question. board: painting. asking: a
# question is on the screen, and nothing else may change there. log: a whole
# log is on the terminal's own screen, where it can be scrolled.
_State = Literal["closed", "pending", "board", "asking", "log"]


@dataclass
class _Mode:
    state: _State = "closed"
    # Somebody may still be typing: false once input has ended.
    read: bool = True

    @property
    def open(self) -> bool:
        return self.state in {"board", "asking", "log"}

    @property
    def paints(self) -> bool:
        return self.state == "board"


@dataclass
class _Loops:
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    painting: asyncio.Task[None] | None = None
    typing: asyncio.Task[None] | None = None

    def drain(self) -> list[asyncio.Task[None]]:
        running = [task for task in (self.painting, self.typing) if task is not None]
        self.painting = self.typing = None
        return running


# The terminal of a cast typed by hand, once it has set other casts going: a
# line per cast, the latest output of one, and one question at a time. It is
# painted whole, and a key needs Enter behind it — no raw mode, no cursor
# arithmetic, as the daemon's own terminal does it. A question takes the view,
# and the board stays as it was until the question closes.
# shortcut: a repaint wipes what is typed but not yet entered from the screen,
# though not from the read. Upgrade to a raw-mode read if that gets in the way.
class Board(Display, Channel):
    def __init__(self, *, screen: Revisable, asker: StandaloneRenderer) -> None:
        self.out = Diverted(screen)
        self.asker = asker
        self._screen = screen
        self._picture = Picture()
        self._mode = _Mode(read=asker.interactive)
        self._loops = _Loops()
        # One question at a time, the typed cast's among them: they share one
        # stdin, and a second one waits its turn.
        self._turn = asyncio.Lock()

    # The typed cast has a place from the start, and is shown once the board is.
    def typed(self, *, cast_id: str, label: str, started_at: datetime) -> None:
        self._picture.typed = cast_id
        self._picture.entries[cast_id] = Entry(
            label=label, started_at=started_at, log=self.out.log
        )

    @override
    def entered(self, *, cast_id: str, label: str, started_at: datetime) -> None:
        log = Log()
        self._picture.entries[cast_id] = Entry(
            label=label,
            started_at=started_at,
            log=log,
            renderer=StandaloneRenderer(out=log),
        )
        if not self._picture.view:
            self._picture.view = cast_id
        if self._mode.open:
            self._loops.changed.set()
        elif self._turn.locked():
            self._mode.state = "pending"
        else:
            self._open()

    @override
    def render(self, cast_id: str, event: RiteEvent) -> None:
        entry = self._picture.entries[cast_id]
        entry.notice = ""
        if isinstance(event, RiteBegan):
            if event.category == "step":
                entry.steps[event.rite_id] = event.name
        elif isinstance(event, RiteEnded):
            entry.steps.pop(event.rite_id, None)
        if entry.renderer is not None:
            entry.renderer.render(event)
        self._loops.changed.set()

    @override
    def ended(self, *, cast_id: str, status: EndStatus, detail: str | None) -> None:
        entry = self._picture.entries[cast_id]
        entry.ended = status
        lines = (detail or "").splitlines()
        entry.notice = next(iter(lines), "")
        if len(lines) > 1:
            entry.log.write(f"{detail}\n")
        following = self._picture.next_running(cast_id)
        if self._picture.view == cast_id and following is not None:
            self._picture.view = following
        self._loops.changed.set()

    @override
    def say(self, *, cast_id: str, label: str, line: str) -> None:
        if (entry := self._picture.entries.get(cast_id)) is None:
            self._picture.note = f"[{label}] {line}"
        else:
            entry.notice = line
            entry.log.write(line + "\n")
        self._loops.changed.set()

    @override
    def asking(self, cast_id: str, rows: int) -> AbstractAsyncContextManager[None]:
        return self._asking(cast_id, rows)

    # The typed cast's own questions, asked where its followed casts' are.
    @override
    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        rows = question_height(prompt, options)
        async with self._asking(self._picture.typed, rows):
            return await self.asker.decide(prompt=prompt, options=options, free=free)

    # Left first, so a question cancelled along with this finds the board gone
    # and starts nothing on it. The read is cancelled, as nothing else ends
    # it; the painting ends itself.
    @override
    async def close(self) -> None:
        typing = self._loops.typing
        running = self._loops.drain()
        self._leave()
        self._loops.changed.set()
        if typing is not None:
            typing.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    @contextlib.asynccontextmanager
    async def _asking(self, cast_id: str | None, rows: int) -> AsyncGenerator[None]:
        async with self._turn:
            try:
                if self._mode.open:
                    await self._hold(cast_id, rows)
                yield
            finally:
                self._let_go()

    # The command read is stopped first, so the answer is not read as a key, and
    # what was typed for it but not entered is dropped.
    async def _hold(self, cast_id: str | None, rows: int) -> None:
        typing, self._loops.typing = self._loops.typing, None
        if typing is not None:
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)
        if not self._mode.open:
            return
        self.asker.discard_typed()
        self._resume()
        if cast_id in self._picture.entries:
            self._picture.view = cast_id
        self._mode.state = "asking"
        self._show(question_rows=rows)

    def _let_go(self) -> None:
        if self._mode.state == "pending":
            self._open()
        elif self._mode.state == "asking":
            self._mode.state = "board"
            if self._loops.typing is None:
                self._loops.typing = self._watched(self._typing())
            self._loops.changed.set()

    def _open(self) -> None:
        self._mode.state = "board"
        self.out.divert()
        self._screen.write(_ALTERNATE)
        self._show()
        self._loops.painting = self._watched(self._painting())
        self._loops.typing = self._watched(self._typing())

    # Back to the plain terminal, with what the board leaves behind on it.
    def _leave(self, *, note: str = "") -> None:
        if not self._mode.open:
            return
        self._mode = _Mode(read=self._mode.read)
        self.out.restore()
        self._screen.write(
            _PLAIN + summary(self._picture, now=datetime.now(UTC)) + note
        )
        self._screen.flush()

    # A loop that dies paints nothing again, and a board left on a picture
    # nobody will change hides the casts it is there to show. The other loop
    # goes with it: a read left behind would take the next question's answer.
    def _watched(self, loop: Coroutine[None, None, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(loop)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self._leave(note=f"{_BROKE}: {error!r}\n")
            for other in self._loops.drain():
                other.cancel()

    # The elapsed column moves whether or not a cast has anything to say, so
    # the wait is bounded. The mode is read again after each wait: a question
    # may have taken the screen meanwhile.
    async def _painting(self) -> None:
        for _ in itertools.takewhile(lambda _: self._mode.open, itertools.count()):
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(_TICK_SECONDS):
                    await self._loops.changed.wait()
            self._loops.changed.clear()
            if self._mode.open:
                # A burst of output is one repaint, not one each.
                await asyncio.sleep(_COALESCE_SECONDS)
            if self._mode.paints:
                self._show()

    # Never starts when stdin is not a terminal, and ends when nobody is typing:
    # the board is still worth painting.
    async def _typing(self) -> None:
        for _ in itertools.takewhile(lambda _: self._mode.read, itertools.count()):
            if (line := await self.asker.line()) is None:
                self._mode.read = False
            else:
                self._read(line)
                self._loops.changed.set()

    def _read(self, line: str) -> None:
        shown = self._picture.shown
        if self._mode.state == "log":
            self._resume()
        elif line.isdecimal() and len(line) <= _MAX_DIGITS:
            if 1 <= int(line) <= len(shown):
                self._picture.view = shown[int(line) - 1]
            else:
                self._picture.note = f"there is no cast {line}"
        elif line.lower() == _LOG:
            self._pause()
        elif line:
            self._picture.note = f"{line!r} is not a key — {KEYS}"

    # The whole log goes to the terminal's own screen, whose scrollback is the
    # pager, and stays there after the board is back.
    def _pause(self) -> None:
        self._mode.state = "log"
        lines = [*whole_log(self._picture.entries[self._picture.view]), _BACK]
        self._screen.write(_PLAIN + "".join(f"{line}\n" for line in lines))
        self._screen.flush()

    def _resume(self) -> None:
        if self._mode.state == "log":
            self._mode.state = "board"
            self._screen.write(_ALTERNATE)

    def _show(self, *, question_rows: int | None = None) -> None:
        self._screen.write(
            frame(
                self._picture,
                now=datetime.now(UTC),
                size=shutil.get_terminal_size(),
                question_rows=question_rows,
            )
        )
        self._screen.flush()
        self._picture.note = ""
