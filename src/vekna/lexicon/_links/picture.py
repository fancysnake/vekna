from dataclasses import dataclass, field
from datetime import datetime

from typing_extensions import override

from vekna.lexicon._pacts import EndStatus

from .follow import ended_said
from .standalone import Revisable, StandaloneRenderer

_HOME = "\x1b[H\x1b[2J"
# The rows under the board that are not the view: a note, the keys, the cursor.
_FOOT_ROWS = 3
_MINUTE = 60
_HOUR = 3600
KEYS = "a number to view a cast · l its whole log · Ctrl-C leaves them running"


# What one cast has said, a line to an item. It takes its last write back as a
# terminal does, so a rite that printed nothing inside itself is one line here.
class Log(Revisable):
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


@dataclass
class Entry:
    label: str
    started_at: datetime
    log: Log = field(default_factory=Log)
    # None for the typed cast, which renders itself and is diverted here.
    renderer: StandaloneRenderer | None = None
    # The steps it is inside of, in the order they began.
    steps: dict[str, str] = field(default_factory=dict)
    ended: EndStatus | None = None
    # What its line says last: a question of its that is not asked here, until
    # it says something more, then why it ended.
    notice: str = ""


# What the board shows: the casts in the order they arrived, the typed one
# among them, and the cast whose latest lines are in view.
@dataclass
class Picture:
    entries: dict[str, Entry] = field(default_factory=dict)
    typed: str | None = None
    view: str = ""
    note: str = ""

    # The typed cast leaves when it ends well: what it set going is what the
    # board is for. One that failed stays, as every failure does.
    @property
    def shown(self) -> list[str]:
        return [
            cast_id
            for cast_id, entry in self.entries.items()
            if cast_id != self.typed or entry.ended != "ok"
        ]

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


def _line(*, index: int, entry: Entry, now: datetime) -> str:
    if entry.ended is not None:
        said = ended_said(entry.ended, entry.notice)
        return f" {index:>2}  {entry.label}  {said}"
    took = _clock((now - entry.started_at).total_seconds())
    step = next(reversed(entry.steps.values()), "")
    return f" {index:>2}  {entry.label}  ▶ {took}  {step}  {entry.notice}".rstrip()


# One screenful, painted over the last: a line per cast, then as much of the
# viewed cast's latest output as the rows left hold. While a question is asked
# the foot is left off and `question_rows` are kept free instead, because the
# question is printed where the foot would be.
def frame(
    picture: Picture,
    *,
    now: datetime,
    size: tuple[int, int],
    question_rows: int | None = None,
) -> str:
    columns, rows = size
    lines = [
        _line(index=index, entry=picture.entries[cast_id], now=now)
        for index, cast_id in enumerate(picture.shown, 1)
    ]
    if (viewed := picture.entries.get(picture.view)) is not None:
        foot = _FOOT_ROWS if question_rows is None else question_rows
        room = max(1, rows - len(lines) - 1 - foot)
        lines += [f"── {viewed.label} ──", *viewed.log.lines[-room:]]
    if question_rows is None:
        lines += [f" {picture.note}" if picture.note else "", f" {KEYS}"]
    return _HOME + "\n".join(_clipped(line, columns) for line in lines) + "\n"


def whole_log(entry: Entry) -> list[str]:
    return [f"── {entry.label} ──", *entry.log.lines]


# What the board leaves on the terminal: what the typed cast said while the
# board had the screen, a line per cast, and every failed cast's log in full.
def summary(picture: Picture, *, now: datetime) -> str:
    entries = picture.entries
    typed = [] if picture.typed is None else entries[picture.typed].log.lines
    listed = [entries[cast_id] for cast_id in picture.shown]
    failed = [
        entries[cast_id]
        for cast_id in picture.shown
        if cast_id != picture.typed and entries[cast_id].ended not in {None, "ok"}
    ]
    lines = [
        *typed,
        *(
            _line(index=index, entry=entry, now=now)
            for index, entry in enumerate(listed, 1)
        ),
        *(line for entry in failed for line in whole_log(entry)),
    ]
    return "".join(f"{line}\n" for line in lines)
