import asyncio
import contextlib
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from typing_extensions import override

from vekna.lexicon._pacts import (
    Channel,
    Display,
    EndStatus,
    LineageProtocol,
    RiteBegan,
    RiteEnded,
    RiteEvent,
    RiteStreamed,
    StandalonePromptError,
)
from vekna.wire import (
    SHORT_ID,
    CastGoodbye,
    CastHello,
    CastMessage,
    DecideClaimed,
    DecideReleased,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    GrimoireBegin,
    GrimoireEnd,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

from .standalone import Out, Revisable, StandaloneRenderer, question_height

_MARK: dict[EndStatus, str] = {
    "ok": "✓ done",
    "error": "✗ failed",
    "disconnected": "⚠ aborted",
}


def ended_said(status: EndStatus, detail: str | None) -> str:
    return f"{_MARK[status]}: {detail}" if detail else _MARK[status]


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


# One followed cast: its name, and the rites it has already shown, so a replay
# after the cast reattaches says nothing twice.
@dataclass
class _Followed:
    label: str
    started: set[str] = field(default_factory=set)
    finished: set[str] = field(default_factory=set)
    # The rites already shown when a replay began; their output in it is old.
    replayed: set[str] | None = None


# The connection to the daemon: written to with answers, read for everything.
@dataclass
class _Wire:
    path: Path
    writer: asyncio.StreamWriter | None = None
    reader: asyncio.Task[None] | None = None


# The prompts of the followed casts, and who is asking each one here.
@dataclass
class _Prompts:
    open: dict[str, DecideRequested] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)
    asking: dict[str, asyncio.Task[None]] = field(default_factory=dict)


# A cast typed by hand, still at its terminal after its own steps: it watches
# the casts it set going, shows what each one does on its display, and asks
# their prompts here — until a surface claims one, which takes it over. A
# surface of the daemon's like any window, so it hears every cast and keeps
# to the ones its lineage says are this cast's.
class Follower:
    def __init__(
        self,
        *,
        socket_path: Path,
        lineage: LineageProtocol,
        display: Display,
        ask: Channel | None,
    ) -> None:
        self._wire = _Wire(path=socket_path)
        self._lineage = lineage
        self._display = display
        self._ask = ask
        self._followed: dict[str, _Followed] = {}
        self._prompts = _Prompts()
        self._done = asyncio.Event()

    async def attach(self) -> bool:
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._wire.path))
        except OSError:
            return False
        self._wire.writer = writer
        writer.write(encode_frame(SurfaceHello()))
        self._wire.reader = asyncio.create_task(self._read(reader))
        return True

    # True once every cast this one set going has ended; False if the daemon
    # went first, and with it any word of how they end. `done` is cleared
    # first: a set from before the cast queued its last child is stale.
    async def until_settled(self) -> bool:
        if not self._lineage.settled and self._wire.writer is not None:
            self._done.clear()
            await self._done.wait()
        return self._lineage.settled

    async def close(self) -> None:
        for task in self._prompts.asking.values():
            task.cancel()
        if (reader := self._wire.reader) is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await self._hang_up()

    async def _hang_up(self) -> None:
        if (writer := self._wire.writer) is not None:
            self._wire.writer = None
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def _read(self, reader: asyncio.StreamReader) -> None:
        with contextlib.suppress(OSError, ValueError):
            async for message in read_frames(reader):
                self._lineage.heard(message)
                self._heard(message)
                # Only a cast arriving or ending can settle the lineage.
                if isinstance(message, CastHello | CastGoodbye) and (
                    self._lineage.settled
                ):
                    self._done.set()
        await self._hang_up()
        self._done.set()

    def _heard(self, message: WireMessage) -> None:
        if not isinstance(message, CastMessage) or not self._lineage.descends(
            message.cast_id
        ):
            return
        match message:
            case CastHello():
                self._hello(message)
            case GrimoireBegin() | GrimoireEnd():
                self._replay(message)
            case RiteStarted() | RiteDelta() | RiteFinished():
                self._rite(message)
            case DecideRequested() | DecideResolved() | DecideWithdrawn():
                self._prompt(message)
            case DecideClaimed():
                self._claim(message)
            case DecideReleased():
                self._release(message)
            case CastGoodbye():
                self._goodbye(message)
            case _:
                pass

    def _hello(self, hello: CastHello) -> None:
        if hello.cast_id in self._followed:
            return
        label = f"{hello.ritual} {hello.cast_id[:SHORT_ID]}"
        self._followed[hello.cast_id] = _Followed(label=label)
        self._display.entered(
            cast_id=hello.cast_id, label=label, started_at=hello.started_at
        )

    def _replay(self, message: GrimoireBegin | GrimoireEnd) -> None:
        if (followed := self._followed.get(message.cast_id)) is not None:
            began = isinstance(message, GrimoireBegin)
            followed.replayed = set(followed.started) if began else None

    def _rite(self, message: RiteStarted | RiteDelta | RiteFinished) -> None:
        if (followed := self._followed.get(message.cast_id)) is None:
            return
        if (event := _event(message, followed)) is not None:
            self._display.render(message.cast_id, event)

    def _goodbye(self, goodbye: CastGoodbye) -> None:
        if goodbye.cast_id in self._followed:
            self._display.ended(
                cast_id=goodbye.cast_id, status=goodbye.status, detail=goodbye.detail
            )

    def _prompt(
        self, message: DecideRequested | DecideResolved | DecideWithdrawn
    ) -> None:
        if isinstance(message, DecideRequested):
            self._prompts.open[message.request_id] = message
            self._start(message.request_id)
            return
        self._prompts.open.pop(message.request_id, None)
        self._prompts.claimed.discard(message.request_id)
        self._stop(message.request_id)

    # A claim takes the prompt from this terminal.
    def _claim(self, message: DecideClaimed) -> None:
        if (request := self._prompts.open.get(message.request_id)) is None:
            return
        self._prompts.claimed.add(message.request_id)
        self._stop(message.request_id)
        self._say(request, f"taken over in `vekna`: {request.prompt}")

    # A release hands the prompt back to this terminal.
    def _release(self, message: DecideReleased) -> None:
        if message.request_id not in self._prompts.open:
            return
        self._prompts.claimed.discard(message.request_id)
        self._start(message.request_id)

    def _start(self, request_id: str) -> None:
        request = self._prompts.open[request_id]
        if request_id in self._prompts.claimed or request_id in self._prompts.asking:
            return
        if (ask := self._ask) is None:
            self._say(request, f"⏸ {request.prompt} — answer it in `vekna`")
            return
        task = asyncio.create_task(self._asked(ask, request))
        self._prompts.asking[request_id] = task
        task.add_done_callback(lambda _: self._prompts.asking.pop(request_id, None))

    def _stop(self, request_id: str) -> None:
        if (task := self._prompts.asking.pop(request_id, None)) is not None:
            task.cancel()

    async def _asked(self, ask: Channel, request: DecideRequested) -> None:
        prompt = f"[{self._label(request.cast_id)}] {request.prompt}"
        try:
            async with self._display.asking(
                request.cast_id, question_height(prompt, request.options)
            ):
                answer = await ask.decide(
                    prompt=prompt, options=request.options, free=request.free
                )
        except StandalonePromptError as error:
            self._say(request, f"{error} — answer it in `vekna`")
            return
        if (writer := self._wire.writer) is not None:
            writer.write(
                encode_frame(
                    DecideResolved(
                        cast_id=request.cast_id,
                        request_id=request.request_id,
                        answer=answer,
                    )
                )
            )

    # The one place a cast not heard from yet gets a name: its short id.
    def _label(self, cast_id: str) -> str:
        followed = self._followed.get(cast_id)
        return cast_id[:SHORT_ID] if followed is None else followed.label

    def _say(self, request: DecideRequested, line: str) -> None:
        self._display.say(
            cast_id=request.cast_id, label=self._label(request.cast_id), line=line
        )


# What a rite message means to a renderer, or None for what it has shown
# already: a rite seen before a replay is not begun again, a rite that has
# ended is not ended twice, and output replayed for a rite already shown is
# output already printed.
def _event(
    message: RiteStarted | RiteDelta | RiteFinished, followed: _Followed
) -> RiteEvent | None:
    rite_id = message.rite_id
    match message:
        case RiteStarted():
            if rite_id in followed.started:
                return None
            followed.started.add(rite_id)
            return RiteBegan(
                rite_id=rite_id,
                parent_id=message.parent_id,
                name=message.name,
                category=message.category,
                started_at=message.started_at,
            )
        case RiteDelta():
            if followed.replayed is not None and rite_id in followed.replayed:
                return None
            return RiteStreamed(rite_id=rite_id, delta=message.delta)
        case _:
            if rite_id in followed.finished:
                return None
            followed.finished.add(rite_id)
            return RiteEnded(
                rite_id=rite_id,
                status=message.status,
                result=message.result,
                finished_at=message.finished_at,
                error=message.error,
            )
