from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from vekna.wire import CastMessage, LichRose, LichUpdate, SurfaceCommand, WireMessage


# Sending is not awaited: a surface owns a queue and a writer task, so a slow
# terminal cannot stall the cast whose event it is being sent.
class Surface(Protocol):
    def send(self, message: WireMessage) -> None: ...


# Something that is not a socket is sitting where the daemon binds. Its own
# error because the answer is a sentence naming the path, not the traceback out
# of `bind()` that would otherwise reach the operator.
class SocketPathError(Exception):
    pass


Action = Literal["applied", "attached", "detached", "dropped"]


# What the daemon did with one message. Emitted for every message, whether or
# not anything came of it: the whole point of --debug is that "the event never
# arrived" and "the handler ignored it" stop looking the same.
# `subject` is who the message was about — a cast id, or a lich's name once the
# daemon routes for liches too. One column either way, because what an operator
# filters a debug log on is "everything to do with that thing".
@dataclass(frozen=True, kw_only=True)
class Routed:
    kind: str
    subject: str | None
    action: Action
    reason: str | None = None


# What the socket has to be able to reach, bundled because there are now three
# kinds of connection on it and seven loose callbacks in a signature is a list
# nobody can read. The server knows which connection said what; everything about
# what that means is on the other side of this.
@dataclass(frozen=True, kw_only=True)
class Wiring:
    on_message: Callable[[CastMessage], None]
    on_attach: Callable[[Surface], None]
    on_detach: Callable[[Surface], None]
    # Returns why a rising was refused, or None once the lich stands. Refused,
    # the connection is closed — which is how the process on the other end
    # learns it is not the lich of that name.
    on_rise: Callable[[LichRose, Surface], str | None]
    on_lich: Callable[[LichUpdate], None]
    on_fallen: Callable[[str], None]
    # A surface with something to say, which until 0.7.0 no surface had.
    on_command: Callable[[SurfaceCommand], None]
