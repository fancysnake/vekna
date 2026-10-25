import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from vekna.lexicon._pacts import (
    Channel,
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

from .standalone import Out, StandaloneRenderer

_MARK = {"ok": "✓ done", "error": "✗ failed", "disconnected": "⚠ aborted"}


# Every line a cast's renderer writes, under the name of the cast that said it:
# several casts stream into one terminal, and indentation is all a line carries.
class _Prefixed:
    def __init__(self, out: Out, label: str) -> None:
        self._out = out
        self._label = f"[{label}] "
        self._fresh = True

    def write(self, text: str, /) -> int:
        for line in text.splitlines(keepends=True):
            if self._fresh:
                self._out.write(self._label)
            self._out.write(line)
            self._fresh = line.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self._out.flush()

    def isatty(self) -> bool:
        return self._out.isatty()


# One followed cast: its renderer, and the rites it has already shown, so a
# replay after the cast reattaches says nothing twice.
@dataclass
class _Followed:
    label: str
    renderer: StandaloneRenderer
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
# the casts it set going, prints what each one does under its name, and asks
# their prompts here — until a surface claims one, which takes it over. A
# surface of the daemon's like any window, so it hears every cast and keeps
# to the ones its lineage says are this cast's.
class Follower:
    def __init__(
        self,
        *,
        socket_path: Path,
        lineage: LineageProtocol,
        out: Out,
        ask: Channel | None,
    ) -> None:
        self._wire = _Wire(path=socket_path)
        self._lineage = lineage
        self._out = out
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
        self._wire.writer = None
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
            case CastGoodbye():
                self._goodbye(message)
            case _:
                pass

    def _hello(self, hello: CastHello) -> None:
        if hello.cast_id in self._followed:
            return
        label = f"{hello.ritual} {hello.cast_id[:SHORT_ID]}"
        self._followed[hello.cast_id] = _Followed(
            label=label, renderer=StandaloneRenderer(out=_Prefixed(self._out, label))
        )

    def _replay(self, message: GrimoireBegin | GrimoireEnd) -> None:
        if (followed := self._followed.get(message.cast_id)) is not None:
            began = isinstance(message, GrimoireBegin)
            followed.replayed = set(followed.started) if began else None

    def _rite(self, message: RiteStarted | RiteDelta | RiteFinished) -> None:
        if (followed := self._followed.get(message.cast_id)) is None:
            return
        if (event := _event(message, followed)) is not None:
            followed.renderer.render(event)

    def _goodbye(self, goodbye: CastGoodbye) -> None:
        if (followed := self._followed.get(goodbye.cast_id)) is None:
            return
        said = f": {goodbye.detail}" if goodbye.detail else ""
        self._say(f"[{followed.label}] {_MARK[goodbye.status]}{said}")

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

    # A claim takes the prompt from this terminal; one let go hands it back.
    def _claim(self, message: DecideClaimed) -> None:
        if (request := self._prompts.open.get(message.request_id)) is None:
            return
        if message.claim_id is None:
            self._prompts.claimed.discard(message.request_id)
            self._start(message.request_id)
            return
        self._prompts.claimed.add(message.request_id)
        self._stop(message.request_id)
        self._say(f"{self._label(request)} taken over in `vekna`: {request.prompt}")

    def _start(self, request_id: str) -> None:
        request = self._prompts.open[request_id]
        if request_id in self._prompts.claimed or request_id in self._prompts.asking:
            return
        if (ask := self._ask) is None:
            self._say(
                f"{self._label(request)} ⏸ {request.prompt} — answer it in `vekna`"
            )
            return
        task = asyncio.create_task(self._asked(ask, request))
        self._prompts.asking[request_id] = task
        task.add_done_callback(lambda _: self._prompts.asking.pop(request_id, None))

    def _stop(self, request_id: str) -> None:
        if (task := self._prompts.asking.pop(request_id, None)) is not None:
            task.cancel()

    async def _asked(self, ask: Channel, request: DecideRequested) -> None:
        try:
            answer = await ask.decide(
                prompt=f"{self._label(request)} {request.prompt}",
                options=request.options,
                free=request.free,
            )
        except StandalonePromptError as error:
            self._say(f"{self._label(request)} {error} — answer it in `vekna`")
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

    def _label(self, request: DecideRequested) -> str:
        followed = self._followed.get(request.cast_id)
        return f"[{request.cast_id[:SHORT_ID] if followed is None else followed.label}]"

    def _say(self, line: str) -> None:
        self._out.write(line + "\n")
        self._out.flush()


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
