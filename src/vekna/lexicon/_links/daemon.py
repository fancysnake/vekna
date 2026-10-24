import asyncio
import contextlib
import itertools
import sys
from collections.abc import AsyncGenerator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, JsonValue, TypeAdapter

from vekna.lexicon._pacts import (
    AskFn,
    CastEnded,
    CastQueueProtocol,
    Channel,
    CodingCall,
    CodingFocusProtocol,
    FocusReply,
    GateFn,
    MediumBoundaryError,
    NoDaemonError,
    RiteBegan,
    RiteEvent,
    RiteStreamed,
    Ritual,
    RitualError,
)
from vekna.wire import (
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    EnqueueAccepted,
    EnqueueRefused,
    EnqueueRequested,
    GrimoireBegin,
    GrimoireEnd,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    WireMessage,
    allowed_answers,
    encode_frame,
    read_frames,
)

_REATTACH_SECONDS = 2.0
_NO_QUEUE = "the queue needs a daemon — run `vekna` to start one"
_GONE_MID_ENQUEUE = "the daemon went away before it said the cast was queued"
_COMPONENTS: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


def to_wire(event: RiteEvent, *, cast_id: str) -> WireMessage:
    if isinstance(event, RiteBegan):
        return RiteStarted(
            cast_id=cast_id,
            rite_id=event.rite_id,
            parent_id=event.parent_id,
            name=event.name,
            category=event.category,
            started_at=event.started_at,
        )
    if isinstance(event, RiteStreamed):
        return RiteDelta(cast_id=cast_id, rite_id=event.rite_id, delta=event.delta)
    return RiteFinished(
        cast_id=cast_id,
        rite_id=event.rite_id,
        status=event.status,
        result=event.result,
        finished_at=event.finished_at,
        error=event.error,
    )


# The cast's end of the wire. It writes what the cast is doing, and reads back
# the two things a daemon has for a cast: an answer to a prompt and a coding
# slot. A grant waited on is let go when the daemon goes, so a dying daemon
# cannot strand a cast at an agent call. An answer is not: the prompt is asked
# again on the next attach, and nobody else can answer it.
# A held slot and a waited one are both said again on a reattach, so a daemon
# started mid-cast counts what is already running before it grants anything.
# shortcut: a slot taken with no daemon attached is asked for again on the next
# attach and counted only once granted, so the daemon can run past its limit
# until then; reporting it as held rather than asked is the upgrade.
class DaemonLink:
    def __init__(self, *, socket_path: Path, hello: CastHello) -> None:
        self._path = socket_path
        self._hello = hello
        self._writer: asyncio.StreamWriter | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._closed = False
        self._pending = _Pending()

    @property
    def hello(self) -> CastHello:
        return self._hello

    @property
    def attached(self) -> bool:
        return self._writer is not None

    def send(self, message: WireMessage) -> None:
        if (writer := self._writer) is not None:
            writer.write(encode_frame(message))

    # Asked again once the connection is up, because `close` can run while this
    # is waiting for it: a cast that ended mid-connect would otherwise leave a
    # socket the daemon never hears a goodbye on, and hold it open until the
    # process exits. The backlog is read once the connection is up, for the same
    # reason: what is sent while connecting is dropped, so a snapshot taken
    # before it would replay a prompt or rite that settled in between.
    async def attach(
        self, *, backlog: Callable[[], Sequence[WireMessage]] = list
    ) -> bool:
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._path))
        except OSError:
            return False
        if self._closed:
            await self._shut(writer)
            return False
        self._writer = writer
        # Every (re)attach replays the whole cast, bracketed — the daemon wipes
        # what it holds for this cast on `GrimoireBegin` and rebuilds it from
        # what follows, so a daemon that started mid-cast is not missing a half.
        self.send(self._hello)
        self.send(GrimoireBegin(cast_id=self._hello.cast_id))
        for message in (
            *backlog(),
            *(slot.request for slot in self._pending.slots.values()),
            *(awaited.request for awaited in self._pending.awaits.values()),
        ):
            self.send(message)
        self.send(GrimoireEnd(cast_id=self._hello.cast_id))
        self._watcher = asyncio.create_task(self._watch(reader))
        return True

    # The probe runs for the life of the cast, not just at the start: a daemon
    # raised while a cast is halfway through picks it up, and one killed under a
    # cast costs the tee and nothing else.
    async def keep_attached(
        self,
        backlog: Callable[[], list[WireMessage]],
        *,
        every: float = _REATTACH_SECONDS,
    ) -> None:
        # A `while` in disguise: pylint's `while_used` bans the statement.
        for _ in itertools.takewhile(lambda _: not self._closed, itertools.count()):
            await asyncio.sleep(every)
            if not self.attached:
                await self.attach(backlog=backlog)

    # The probe stops here too: a cast that has said goodbye has nothing left to
    # tell a daemon that turns up afterwards.
    async def close(
        self,
        *,
        status: Literal["ok", "error"],
        detail: str | None = None,
        result: JsonValue | None = None,
    ) -> None:
        self._closed = True
        if (watcher := self._watcher) is not None:
            # It is waiting on an EOF that is not coming: this end is the one
            # ending, and the read would outlive the cast that started it.
            watcher.cancel()
            self._watcher = None
        if self._writer is None:
            return
        self.send(
            CastGoodbye(
                cast_id=self._hello.cast_id, status=status, detail=detail, result=result
            )
        )
        writer, self._writer = self._writer, None
        await self._shut(writer)

    # The answer to `request`, from whichever surface gives one the prompt
    # allows. Sent as well as awaited here, so a prompt is never on the wire
    # without somebody listening for what comes back.
    async def answer(self, request: DecideRequested) -> str:
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        awaited = _Awaited(
            future=future,
            allowed=allowed_answers(options=request.options, free=request.free),
        )
        self._pending.answers[request.request_id] = awaited
        self.send(request)
        try:
            return await awaited.future
        finally:
            self._pending.answers.pop(request.request_id, None)

    # Held for as long as the block runs. With no daemon there is nobody to
    # share with, so there is no limit to wait on.
    @contextlib.asynccontextmanager
    async def coding(self) -> AsyncGenerator[None]:
        slot = _Slot(
            request=CodingSlotRequested(
                cast_id=self._hello.cast_id, request_id=uuid4().hex
            )
        )
        self._pending.slots[slot.request.request_id] = slot
        try:
            if self.attached:
                slot.granted = asyncio.get_running_loop().create_future()
                self.send(slot.request)
                await slot.granted
            yield
        finally:
            del self._pending.slots[slot.request.request_id]
            self.send(
                CodingSlotReleased(
                    cast_id=self._hello.cast_id, request_id=slot.request.request_id
                )
            )

    # Queued once the daemon says so. A daemon gone before it answers may have
    # queued it or not, and this cast cannot tell which.
    async def enqueue(self, hello: CastHello) -> None:
        if not self.attached:
            raise NoDaemonError(_NO_QUEUE)
        request = EnqueueRequested(
            cast_id=self._hello.cast_id, request_id=uuid4().hex, hello=hello
        )
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._pending.enqueues[request.request_id] = future
        self.send(request)
        try:
            await future
        finally:
            del self._pending.enqueues[request.request_id]

    # Outlives the connection: said again on every reattach, and answered by
    # whichever daemon is there when the child ends, off its journal if need be.
    # A wait given up is withdrawn; the child runs on regardless.
    async def await_end(self, child: str) -> AwaitEnded:
        if not self.attached:
            raise NoDaemonError(_NO_QUEUE)
        request = AwaitRequested(
            cast_id=self._hello.cast_id, request_id=uuid4().hex, child=child
        )
        ended: asyncio.Future[AwaitEnded] = asyncio.get_running_loop().create_future()
        awaited = _Await(request=request, ended=ended)
        self._pending.awaits[request.request_id] = awaited
        self.send(request)
        try:
            return await awaited.ended
        except asyncio.CancelledError:
            self.send(
                AwaitWithdrawn(
                    cast_id=self._hello.cast_id, request_id=request.request_id
                )
            )
            raise
        finally:
            del self._pending.awaits[request.request_id]

    # A daemon that goes away is as likely to reset the connection as to close
    # it cleanly, and either way this is how the cast finds out. The detach has
    # to happen whichever arrives, or a link keeps writing into a socket nobody
    # holds and the cast believes it is still attached. A frame it cannot read
    # is a daemon it cannot talk to, and ends the same way.
    async def _watch(self, reader: asyncio.StreamReader) -> None:
        with contextlib.suppress(OSError, ValueError):
            async for message in read_frames(reader):
                self._heard(message)
        self._detach()

    def _heard(self, message: WireMessage) -> None:
        if isinstance(message, DecideResolved):
            self._answered(message)
        elif (
            isinstance(message, CodingSlotGranted)
            and (slot := self._pending.slots.get(message.request_id)) is not None
            and slot.granted is not None
        ):
            _settle(slot.granted)
        elif isinstance(message, EnqueueAccepted | EnqueueRefused):
            self._enqueued(message)
        elif (
            isinstance(message, AwaitEnded)
            and (awaited := self._pending.awaits.get(message.request_id)) is not None
            and not awaited.ended.done()
        ):
            awaited.ended.set_result(message)

    def _enqueued(self, message: EnqueueAccepted | EnqueueRefused) -> None:
        if (
            future := self._pending.enqueues.get(message.request_id)
        ) is None or future.done():
            return
        if isinstance(message, EnqueueRefused):
            future.set_exception(RitualError(f"not queued: {message.reason}"))
        else:
            future.set_result(None)

    # An answer the prompt does not allow is refused here and the prompt stays
    # open: the dashboard checks before it sends, so this is somebody else
    # writing to the socket, and the cast says so where its output goes.
    def _answered(self, message: DecideResolved) -> None:
        if (awaited := self._pending.answers.get(message.request_id)) is None:
            return
        if awaited.allowed is not None and message.answer not in awaited.allowed:
            sys.stderr.write(
                f"refused answer {message.answer!r}:"
                f" not one of {', '.join(awaited.allowed)}\n"
            )
            return
        if not awaited.future.done():
            awaited.future.set_result(message.answer)

    def _detach(self) -> None:
        self._writer = None
        for slot in self._pending.slots.values():
            if slot.granted is not None:
                _settle(slot.granted)
        for future in self._pending.enqueues.values():
            if not future.done():
                future.set_exception(NoDaemonError(_GONE_MID_ENQUEUE))

    @staticmethod
    async def _shut(writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(OSError):
            await writer.drain()
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


@dataclass(frozen=True, kw_only=True)
class _Awaited:
    future: asyncio.Future[str]
    allowed: tuple[str, ...] | None


# A coding slot this cast holds or is waiting for. `granted` is what the wait is
# on, and there is none for a slot taken with no daemon to ask.
@dataclass(kw_only=True)
class _Slot:
    request: CodingSlotRequested
    granted: asyncio.Future[None] | None = None


@dataclass(frozen=True, kw_only=True)
class _Await:
    request: AwaitRequested
    ended: asyncio.Future[AwaitEnded]


# Everything the cast is waiting on the daemon for, by request.
@dataclass(kw_only=True)
class _Pending:
    answers: dict[str, _Awaited] = field(default_factory=dict)
    slots: dict[str, _Slot] = field(default_factory=dict)
    enqueues: dict[str, asyncio.Future[None]] = field(default_factory=dict)
    awaits: dict[str, _Await] = field(default_factory=dict)


def _settle(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


# A cast run by hand keeps its prompt where it is: this asks whatever the cast
# would have asked anyway — the standalone renderer, one stdin — and tells the
# daemon a prompt is open on either side of the wait, so a surface can raise a
# waiting cast and then stop raising it. A spawned cast has no stdin, so with no
# `inner` the answer comes over the wire from a surface instead.
class TeeChannel(Channel):
    def __init__(
        self,
        *,
        inner: Channel | None,
        link: DaemonLink,
        cast_id: str,
        rite_id: Callable[[], str | None],
    ) -> None:
        self._inner = inner
        self._link = link
        self._cast_id = cast_id
        self._rite_id = rite_id
        self._open: dict[str, DecideRequested] = {}

    # What a mid-cast attach has to say again: the daemon learns the rites from
    # the grimoire, but a prompt already on screen is not in it.
    def open_prompts(self) -> list[WireMessage]:
        return list(self._open.values())

    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        request = DecideRequested(
            cast_id=self._cast_id,
            rite_id=self._rite_id(),
            request_id=uuid4().hex,
            prompt=prompt,
            options=None if options is None else list(options),
            free=free,
        )
        self._open[request.request_id] = request
        try:
            if (inner := self._inner) is None:
                answer = await self._link.answer(request)
            else:
                self._link.send(request)
                answer = await inner.decide(prompt=prompt, options=options, free=free)
        except BaseException:
            self._link.send(
                DecideWithdrawn(cast_id=self._cast_id, request_id=request.request_id)
            )
            raise
        finally:
            self._open.pop(request.request_id, None)
        self._link.send(
            DecideResolved(
                cast_id=self._cast_id, request_id=request.request_id, answer=answer
            )
        )
        return answer


# Where the queue mediums reach the daemon. The child's hello is built here, by
# the cast that has the ritual and the model: the daemon loads neither. The
# name is resolved first, so what is queued is a name meaning one ritual from
# anywhere, and the child runs in the tree this cast was asked from.
class LinkQueue(CastQueueProtocol):
    def __init__(self, *, link: DaemonLink, ritual: Callable[[str], Ritual]) -> None:
        self._link = link
        self._ritual = ritual

    async def enqueue(self, *, ritual: str, components: BaseModel) -> str:
        found = self._ritual(ritual)
        if not isinstance(components, found.components):
            msg = (
                f"{found.name} takes {found.components.__name__},"
                f" not {type(components).__name__}"
            )
            raise MediumBoundaryError(msg)
        parent = self._link.hello
        hello = CastHello(
            cast_id=uuid4().hex,
            project_root=parent.project_root,
            project=parent.project,
            ritual=found.name,
            components=_COMPONENTS.validate_json(components.model_dump_json()),
            started_at=datetime.now(tz=UTC),
            wired=True,
            enqueued_by=parent.cast_id,
            worktree=found.worktree,
        )
        await self._link.enqueue(hello)
        return hello.cast_id

    async def await_end(self, cast_id: str) -> CastEnded:
        ended = await self._link.await_end(cast_id)
        return CastEnded(status=ended.status, detail=ended.detail, result=ended.result)


# The coding focus a cast registered, behind the daemon's coding limit: every
# agent session waits for a slot and holds it until the session ends. Only
# `coding` is throttled — a medium a human drives as it runs has the human for
# a limit.
class ThrottledFocus(CodingFocusProtocol):
    def __init__(self, *, inner: CodingFocusProtocol, link: DaemonLink) -> None:
        self._inner = inner
        self._link = link

    async def run(
        self,
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        async with self._link.coding():
            return await self._inner.run(call, on_delta=on_delta, gate=gate, ask=ask)
