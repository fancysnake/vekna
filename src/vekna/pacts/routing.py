from dataclasses import dataclass
from typing import Literal, Protocol

from vekna.wire import (
    CastCancelRequested,
    CastMessage,
    CastRequested,
    DecideClaimed,
    DecideResolved,
    WireMessage,
)


# Sending is not awaited: a surface owns a queue and a writer task, so a slow
# terminal cannot stall the cast whose event it is being sent.
class Surface(Protocol):
    def send(self, message: WireMessage) -> None: ...


# Everything a connection can bring the daemon, once its first frame has said
# what it is. A cast is `apply`d and has a peer the daemon can write back to; a
# surface is attached, and can ask for a cast, claim a prompt, answer one and
# cancel a cast.
class Routes(Protocol):
    def apply(self, message: CastMessage) -> None: ...
    def attach_surface(self, surface: Surface) -> None: ...
    def detach_surface(self, surface: Surface) -> None: ...
    def request(self, surface: Surface, request: CastRequested) -> None: ...
    def answer(self, surface: Surface, resolved: DecideResolved) -> None: ...
    def claim(self, surface: Surface, claimed: DecideClaimed) -> None: ...
    def cancel(self, surface: Surface, cancel: CastCancelRequested) -> None: ...
    def open_cast(self, cast_id: str, peer: Surface) -> None: ...
    def close_cast(self, cast_id: str, peer: Surface) -> None: ...


# Something that is not a socket is sitting where the daemon binds. Its own
# error because the answer is a sentence naming the path, not the traceback out
# of `bind()` that would otherwise reach the operator.
class SocketPathError(Exception):
    pass


Action = Literal["applied", "attached", "detached", "dropped"]


# What the daemon did with one message. Emitted for every message, whether or
# not anything came of it: the whole point of --debug is that "the event never
# arrived" and "the handler ignored it" stop looking the same.
@dataclass(frozen=True, kw_only=True)
class Routed:
    kind: str
    cast_id: str | None
    action: Action
    reason: str | None = None
