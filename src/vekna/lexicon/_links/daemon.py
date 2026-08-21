import asyncio
import contextlib
import itertools
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal
from uuid import uuid4

from vekna.lexicon._pacts import (
    Channel,
    GrimoireEvent,
    RiteBegan,
    RiteStreamed,
    StatusSet,
)
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastStatus,
    DecideRequested,
    DecideResolved,
    GrimoireBegin,
    GrimoireEnd,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    WireMessage,
    encode_frame,
)

_REATTACH_SECONDS = 2.0


def to_wire(event: GrimoireEvent, *, cast_id: str) -> WireMessage:
    if isinstance(event, StatusSet):
        return CastStatus(cast_id=cast_id, text=event.text, at=event.at)
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
    )


# The cast's end of the wire, and send-only: it writes what the cast is doing
# and reads the socket for one thing, the EOF that says the daemon has gone. A
# cast that awaited the daemon for anything would be a cast a dying daemon could
# strand, and there is nothing it needs back.
class DaemonLink:
    def __init__(self, *, socket_path: Path, hello: CastHello) -> None:
        self._path = socket_path
        self._hello = hello
        self._writer: asyncio.StreamWriter | None = None
        self._watcher: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def attached(self) -> bool:
        return self._writer is not None

    def send(self, message: WireMessage) -> None:
        if (writer := self._writer) is not None:
            writer.write(encode_frame(message))

    # Asked again once the connection is up, because `close` can run while this
    # is waiting for it: a cast that ended mid-connect would otherwise leave a
    # socket the daemon never hears a goodbye on, and hold it open until the
    # process exits.
    async def attach(self, *, backlog: Sequence[WireMessage] = ()) -> bool:
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
        for message in backlog:
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
                await self.attach(backlog=backlog())

    # The probe stops here too: a cast that has said goodbye has nothing left to
    # tell a daemon that turns up afterwards.
    async def close(
        self, *, status: Literal["ok", "error"], detail: str | None = None
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
            CastGoodbye(cast_id=self._hello.cast_id, status=status, detail=detail)
        )
        writer, self._writer = self._writer, None
        await self._shut(writer)

    # A daemon that goes away is as likely to reset the connection as to close
    # it cleanly, and either way this is how the cast finds out. The detach has
    # to happen whichever arrives, or a link keeps writing into a socket nobody
    # holds and the cast believes it is still attached.
    async def _watch(self, reader: asyncio.StreamReader) -> None:
        with contextlib.suppress(OSError):
            await reader.read()
        self._detach()

    def _detach(self) -> None:
        self._writer = None

    @staticmethod
    async def _shut(writer: asyncio.StreamWriter) -> None:
        with contextlib.suppress(OSError):
            await writer.drain()
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


# The prompt stays where the cast is. This asks whatever the cast would have
# asked anyway — the standalone renderer, one stdin — and tells the daemon a
# prompt is open on either side of the wait, so a surface can raise a waiting
# cast and then stop raising it.
class TeeChannel(Channel):
    def __init__(
        self,
        *,
        inner: Channel,
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
        self._link.send(request)
        try:
            answer = await self._inner.decide(prompt=prompt, options=options, free=free)
        finally:
            self._open.pop(request.request_id, None)
        self._link.send(
            DecideResolved(
                cast_id=self._cast_id, request_id=request.request_id, answer=answer
            )
        )
        return answer
