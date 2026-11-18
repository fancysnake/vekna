import contextlib
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime

from typing_extensions import override

from vekna.lexicon._pacts import Display, EndStatus, RiteEvent

from .picture import ended_said
from .standalone import Out, Revisable, StandaloneRenderer


# Every line a cast's renderer writes, under the name of the cast that said it:
# several casts stream into one terminal, and indentation is all a line carries.
class _Prefixed(Revisable):
    def __init__(self, out: Revisable, label: str) -> None:
        self._out = out
        self._label = f"[{label}] "
        self._fresh = True

    def _labelled(self, text: str, *, fresh: bool) -> str:
        labelled = []
        for line in text.splitlines(keepends=True):
            labelled.append(f"{self._label}{line}" if fresh else line)
            fresh = line.endswith("\n")
        return "".join(labelled)

    @override
    def write(self, text: str, /) -> int:
        if text:
            self._out.write(self._labelled(text, fresh=self._fresh))
            self._fresh = text.endswith("\n")
        return len(text)

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

    @override
    def overwrite(self, mark: int, text: str) -> bool:
        return self._out.overwrite(mark, self._labelled(text, fresh=True))


# One cast's lines on a stream: straight out on its turn, kept until then. A
# stream takes no line back, so neither does this.
class _Held(Revisable):
    def __init__(self, out: Out) -> None:
        self._out = out
        self._kept: list[str] | None = []

    def release(self) -> None:
        kept, self._kept = self._kept or [], None
        for text in kept:
            self._out.write(text)
        self._out.flush()

    @override
    def write(self, text: str, /) -> int:
        if self._kept is None:
            return self._out.write(text)
        self._kept.append(text)
        return len(text)

    @override
    def flush(self) -> None:
        if self._kept is None:
            self._out.flush()

    @override
    def isatty(self) -> bool:
        return False

    @property
    @override
    def mark(self) -> int:
        return 0

    @override
    def overwrite(self, mark: int, text: str) -> bool:
        return False


@dataclass
class _Turn:
    label: str
    held: _Held
    renderer: StandaloneRenderer
    ended: bool = False


# Several casts into one stream, a cast at a time: a pipe or a log file has no
# cursor to keep them apart with, so the first to arrive speaks until it ends
# and the others are held, then the next in arrival order. A notice about a
# question is said at once whoever is speaking, because the cast that asked
# waits on it.
class Turns(Display):
    def __init__(self, out: Out) -> None:
        self._out = out
        self._turns: dict[str, _Turn] = {}

    @override
    def entered(self, *, cast_id: str, label: str, started_at: datetime) -> None:
        held = _Held(self._out)
        self._turns[cast_id] = _Turn(
            label=label,
            held=held,
            renderer=StandaloneRenderer(out=_Prefixed(held, label)),
        )
        self._pass_on()

    @override
    def render(self, cast_id: str, event: RiteEvent) -> None:
        self._turns[cast_id].renderer.render(event)

    @override
    def ended(self, *, cast_id: str, status: EndStatus, detail: str | None) -> None:
        turn = self._turns[cast_id]
        turn.held.write(f"[{turn.label}] {ended_said(status, detail)}\n")
        turn.held.flush()
        turn.ended = True
        self._pass_on()

    @override
    def say(self, *, cast_id: str, label: str, line: str) -> None:
        del cast_id
        self._out.write(f"[{label}] {line}\n")
        self._out.flush()

    @override
    def asking(self, cast_id: str, rows: int) -> AbstractAsyncContextManager[None]:
        return contextlib.nullcontext()

    # Whatever is still held is said: the follow ended first, and a line kept
    # back would be a line lost. Whoever made the turns closes them.
    @override
    async def close(self) -> None:
        for turn in self._turns.values():
            turn.held.release()

    def _pass_on(self) -> None:
        for turn in self._turns.values():
            turn.held.release()
            if not turn.ended:
                return
