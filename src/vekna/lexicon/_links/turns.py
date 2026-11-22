from dataclasses import dataclass

from typing_extensions import override

from vekna.lexicon._pacts import Display, RiteEvent

from .standalone import Revisable, StandaloneRenderer


# A name or a notice never lands on the end of a line left unfinished.
def _begin_row(out: Revisable) -> None:
    if not out.row_empty:
        out.write("\n")


# Whose line the stream's last one was.
@dataclass
class _Floor:
    speaker: str


# One cast's lines on the stream it shares, under its name whenever the line
# before was another cast's. A line of another cast's is a write of its own, so
# nothing of this cast's goes back over it.
class _Named(Revisable):
    def __init__(self, out: Revisable, *, label: str, floor: _Floor) -> None:
        self._out = out
        self._label = label
        self._floor = floor

    @override
    def write(self, text: str, /) -> int:
        if text and self._floor.speaker != self._label:
            self._floor.speaker = self._label
            _begin_row(self._out)
            self._out.write(f"── {self._label} ──\n")
        return self._out.write(text)

    @override
    def flush(self) -> None:
        self._out.flush()

    @override
    def isatty(self) -> bool:
        return self._out.isatty()

    @property
    @override
    def mark(self) -> int:
        return self._out.mark

    @property
    @override
    def row_empty(self) -> bool:
        return self._out.row_empty

    @override
    def overwrite(self, mark: int, text: str) -> bool:
        return self._out.overwrite(mark, text)


# A typed cast and the casts it set going, into the one stream of its terminal.
# The daemon runs them one at a time, so each line goes straight out, and a
# cast is named where it takes over from another. The typed cast speaks first
# and needs no name until another has spoken. A notice about a cast is a line
# carrying its name: it is not that cast speaking.
class Turns(Display):
    def __init__(self, out: Revisable, *, typed: str) -> None:
        self._out = out
        self._floor = _Floor(speaker=typed)
        self._turns: dict[str, StandaloneRenderer] = {}
        # Where the typed cast writes, and the renderer that shows its rites.
        self.typed: Revisable = _Named(out, label=typed, floor=self._floor)
        self.renderer = StandaloneRenderer(out=self.typed)

    @override
    def entered(self, *, cast_id: str, label: str) -> None:
        out = _Named(self._out, label=label, floor=self._floor)
        self._turns[cast_id] = StandaloneRenderer(out=out)

    @override
    def render(self, cast_id: str, event: RiteEvent) -> None:
        self._turns[cast_id].render(event)

    @override
    def say(self, *, label: str, line: str) -> None:
        _begin_row(self._out)
        self._out.write(f"[{label}] {line}\n")
        self._out.flush()
