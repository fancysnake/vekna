import asyncio
import contextlib
import itertools
import shutil
from collections.abc import AsyncGenerator, Coroutine, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime

from typing_extensions import override

from vekna.lexicon._pacts import (
    Channel,
    Display,
    EndStatus,
    RiteBegan,
    RiteEnded,
    RiteEvent,
)

from .follow import ended_said
from .standalone import Revisable, StandaloneRenderer

_ALTERNATE = "\x1b[?1049h"
_PLAIN = "\x1b[?1049l"
_HOME = "\x1b[H\x1b[2J"
# Long enough that a streaming rite does not repaint per line, short enough that
# the board reads as live.
_COALESCE_SECONDS = 0.1
# How often a board with nothing happening on it repaints anyway, which is what
# makes the elapsed column a clock.
_TICK_SECONDS = 1.0
# The rows under the board that are not the view: a note, the keys, the cursor.
_FOOT_ROWS = 3
# The same, while a question is asked there: its prompt, its options, the answer.
_ASK_ROWS = 8
_MINUTE = 60
_HOUR = 3600
_MAX_DIGITS = 4
_LOG = "l"
_PAINTING = "painting"
_TYPING = "typing"
_KEYS = "a number to view a cast · l its whole log · Ctrl-C leaves them running"
_BACK = "— Enter returns to the board —"
_BROKE = "the board stopped"


# What one cast has said, a line to an item. It takes its last write back as a
# terminal does, so a rite that printed nothing inside itself is one line here.
class _Log(Revisable):
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._mark = 0
        self._added = 0
        self._row_empty = True
        self._began_row = True

    # Counted down: a mark the terminal gave before this log took over the
    # typed cast's lines never names a write made here.
    @property
    @override
    def mark(self) -> int:
        return self._mark

    @override
    def write(self, text: str, /) -> int:
        if not text:
            return 0
        self._mark -= 1
        self._began_row = self._row_empty
        before = len(self.lines)
        for line in text.splitlines(keepends=True):
            if self._row_empty:
                self.lines.append("")
            self.lines[-1] += line.removesuffix("\n")
            self._row_empty = line.endswith("\n")
        self._added = len(self.lines) - before
        return len(text)

    @override
    def flush(self) -> None:
        return

    @override
    def isatty(self) -> bool:
        return True

    @override
    def overwrite(self, mark: int, text: str) -> bool:
        if mark != self._mark or not self._began_row:
            return False
        del self.lines[len(self.lines) - self._added :]
        self._row_empty = True
        self.write(text)
        return True


# What the typed cast writes to: its terminal, until the board takes the screen
# and its lines go to its place on the board instead.
class Diverted(Revisable):
    def __init__(self, screen: Revisable) -> None:
        self.log = _Log()
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


@dataclass
class _Entry:
    label: str
    started_at: datetime
    log: _Log = field(default_factory=_Log)
    # None for the typed cast, which renders itself and is diverted here.
    renderer: StandaloneRenderer | None = None
    # The steps it is inside of, in the order they began.
    steps: dict[str, str] = field(default_factory=dict)
    ended: EndStatus | None = None
    # What its line says last: a question of its that is not asked here, until
    # it says something more, then why it ended.
    notice: str = ""

    # The typed cast leaves when it ends well: what it set going is what the
    # board is for. One that failed stays, as every failure does.
    @property
    def on_board(self) -> bool:
        return self.renderer is not None or self.ended != "ok"


# What the board shows: the casts in the order they arrived, the typed one
# among them, and the cast whose latest lines are in view.
@dataclass
class Picture:
    entries: dict[str, _Entry] = field(default_factory=dict)
    typed: str | None = None
    view: str = ""
    note: str = ""

    @property
    def shown(self) -> list[str]:
        return [cast_id for cast_id, entry in self.entries.items() if entry.on_board]

    # The cast still running that arrived next after this one, around the end.
    def next_running(self, cast_id: str) -> str | None:
        order = list(self.entries)
        at = order.index(cast_id)
        return next(
            (
                other
                for other in (*order[at + 1 :], *order[:at])
                if self.entries[other].ended is None
            ),
            None,
        )


@dataclass
class _Mode:
    open: bool = False
    # Somebody may still be typing: false once input has ended.
    read: bool = True
    # A question is on the screen, and nothing else may change there.
    held: bool = False
    # A whole log is on the terminal's own screen, where it can be scrolled.
    paused: bool = False
    # A cast arrived while a question was on the plain terminal: open after it.
    late: bool = False

    @property
    def paints(self) -> bool:
        return self.open and not self.held and not self.paused


@dataclass
class _Loops:
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)


def _clock(seconds: float) -> str:
    whole = max(0, int(seconds))
    if whole < _MINUTE:
        return f"{whole}s"
    if whole < _HOUR:
        return f"{whole // _MINUTE}m{whole % _MINUTE:02d}s"
    return f"{whole // _HOUR}h{whole % _HOUR // _MINUTE:02d}m"


# shortcut: counts characters as one cell, so a wide character or a colour
# sequence in a cast's output can wrap a row. Upgrade if that shows up.
def _clipped(line: str, columns: int) -> str:
    return line if len(line) <= columns else f"{line[: columns - 1]}…"


def _line(index: int, entry: _Entry, now: datetime) -> str:
    if entry.ended is not None:
        said = ended_said(entry.ended, entry.notice)
        return f" {index:>2}  {entry.label}  {said}"
    took = _clock((now - entry.started_at).total_seconds())
    step = next(reversed(entry.steps.values()), "")
    return f" {index:>2}  {entry.label}  ▶ {took}  {step}  {entry.notice}".rstrip()


# One screenful, painted over the last: a line per cast, then as much of the
# viewed cast's latest output as the rows left hold. While a question is asked
# the foot is left off, because the question is printed where it would be.
def frame(
    picture: Picture, *, now: datetime, size: tuple[int, int], asking: bool = False
) -> str:
    columns, rows = size
    lines = [
        _line(index, picture.entries[cast_id], now)
        for index, cast_id in enumerate(picture.shown, 1)
    ]
    if (viewed := picture.entries.get(picture.view)) is not None:
        foot = _ASK_ROWS if asking else _FOOT_ROWS
        room = max(1, rows - len(lines) - 1 - foot)
        lines += [f"── {viewed.label} ──", *viewed.log.lines[-room:]]
    if not asking:
        lines += [f" {picture.note}" if picture.note else "", f" {_KEYS}"]
    return _HOME + "\n".join(_clipped(line, columns) for line in lines) + "\n"


def _whole_log(entry: _Entry) -> list[str]:
    return [f"── {entry.label} ──", *entry.log.lines]


# What the board leaves on the terminal: what the typed cast said while the
# board had the screen, a line per cast, and every failed cast's log in full.
def summary(picture: Picture, *, now: datetime) -> str:
    entries = picture.entries
    typed = [] if picture.typed is None else entries[picture.typed].log.lines
    listed = [entries[cast_id] for cast_id in picture.shown]
    failed = [
        entry
        for entry in listed
        if entry.renderer is not None and entry.ended not in {None, "ok"}
    ]
    lines = [
        *typed,
        *(_line(index, entry, now) for index, entry in enumerate(listed, 1)),
        *(line for entry in failed for line in _whole_log(entry)),
    ]
    return "".join(f"{line}\n" for line in lines)


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
        self._mode = _Mode()
        self._loops = _Loops()
        # One question at a time, the typed cast's among them: they share one
        # stdin, and a second one waits its turn.
        self._turn = asyncio.Lock()

    # The typed cast has a place from the start, and is shown once the board is.
    def typed(self, *, cast_id: str, label: str, started_at: datetime) -> None:
        self._picture.typed = cast_id
        self._picture.entries[cast_id] = _Entry(
            label=label, started_at=started_at, log=self.out.log
        )

    @override
    def entered(self, *, cast_id: str, label: str, started_at: datetime) -> None:
        log = _Log()
        self._picture.entries[cast_id] = _Entry(
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
            self._mode.late = True
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
        entry.notice = next(iter((detail or "").splitlines()), "")
        following = self._picture.next_running(cast_id)
        if self._picture.view == cast_id and following is not None:
            self._picture.view = following
        self._loops.changed.set()

    @override
    def say(self, cast_id: str, line: str) -> None:
        if (entry := self._picture.entries.get(cast_id)) is None:
            self._picture.note = line
        else:
            entry.notice = line
            entry.log.write(line + "\n")
        self._loops.changed.set()

    @override
    def asking(self, cast_id: str) -> AbstractAsyncContextManager[None]:
        return self._asking(cast_id)

    # The typed cast's own questions, asked where its followed casts' are.
    @override
    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        async with self._asking(self._picture.typed):
            return await self.asker.decide(prompt=prompt, options=options, free=free)

    # Left first, so a question cancelled along with this finds the board gone
    # and starts nothing on it. The read is cancelled, as nothing else ends
    # it; the painting ends itself.
    @override
    async def close(self) -> None:
        tasks, self._loops.tasks = self._loops.tasks, {}
        self._leave()
        self._loops.changed.set()
        if (typing := tasks.get(_TYPING)) is not None:
            typing.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)

    @contextlib.asynccontextmanager
    async def _asking(self, cast_id: str | None) -> AsyncGenerator[None]:
        async with self._turn:
            if self._mode.open:
                await self._hold(cast_id)
            try:
                yield
            finally:
                self._let_go()

    # The command read is stopped first, so the answer is not read as a key.
    async def _hold(self, cast_id: str | None) -> None:
        typing = self._loops.tasks.pop(_TYPING)
        typing.cancel()
        await asyncio.gather(typing, return_exceptions=True)
        self._resume()
        if cast_id in self._picture.entries:
            self._picture.view = cast_id
        self._mode.held = True
        self._show(asking=True)

    def _let_go(self) -> None:
        if self._mode.late:
            self._mode.late = False
            self._open()
        elif self._mode.held:
            self._mode.held = False
            self._loops.tasks[_TYPING] = self._watched(self._typing())
            self._loops.changed.set()

    def _open(self) -> None:
        self._mode.open = True
        self.out.divert()
        self._screen.write(_ALTERNATE)
        self._show()
        self._loops.tasks = {
            _PAINTING: self._watched(self._painting()),
            _TYPING: self._watched(self._typing()),
        }

    # Back to the plain terminal, with what the board leaves behind on it.
    def _leave(self, *, note: str = "") -> None:
        if not self._mode.open:
            return
        self._mode = _Mode()
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
            tasks, self._loops.tasks = self._loops.tasks, {}
            for other in tasks.values():
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

    # Ends when nobody is typing: the board is still worth painting.
    async def _typing(self) -> None:
        for _ in itertools.takewhile(lambda _: self._mode.read, itertools.count()):
            if (line := await self.asker.line()) is None:
                self._mode.read = False
            else:
                self._read(line)
                self._loops.changed.set()

    def _read(self, line: str) -> None:
        shown = self._picture.shown
        if self._mode.paused:
            self._resume()
        elif line.isdecimal() and len(line) <= _MAX_DIGITS:
            if 1 <= int(line) <= len(shown):
                self._picture.view = shown[int(line) - 1]
            else:
                self._picture.note = f"there is no cast {line}"
        elif line.lower() == _LOG:
            self._pause()
        elif line:
            self._picture.note = f"{line!r} is not a key — {_KEYS}"

    # The whole log goes to the terminal's own screen, whose scrollback is the
    # pager, and stays there after the board is back.
    def _pause(self) -> None:
        self._mode.paused = True
        lines = [*_whole_log(self._picture.entries[self._picture.view]), _BACK]
        self._screen.write(_PLAIN + "".join(f"{line}\n" for line in lines))
        self._screen.flush()

    def _resume(self) -> None:
        if self._mode.paused:
            self._mode.paused = False
            self._screen.write(_ALTERNATE)

    def _show(self, *, asking: bool = False) -> None:
        self._screen.write(
            frame(
                self._picture,
                now=datetime.now(UTC),
                size=shutil.get_terminal_size(),
                asking=asking,
            )
        )
        self._screen.flush()
        self._picture.note = ""
