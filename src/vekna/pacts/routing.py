from dataclasses import dataclass
from typing import Literal, Protocol

from vekna.wire import WireMessage


# Sending is not awaited: a surface owns a queue and a writer task, so a slow
# terminal cannot stall the cast whose event it is being sent.
class Surface(Protocol):
    def send(self, message: WireMessage) -> None: ...


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
