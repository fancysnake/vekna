from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


# Where a question went: the thread it was posted in and its message there, as
# the remote names them.
@dataclass(frozen=True, kw_only=True)
class Posted:
    thread: str
    message: str


# What somebody wrote in a thread. `reply_to` is the message it answers, when
# the remote says which.
@dataclass(frozen=True, kw_only=True)
class Heard:
    thread: str
    reply_to: str | None
    text: str


# What is said back to the author, or `None` for nothing.
Hear = Callable[[Heard], Awaitable[str | None]]


# The remote refused, or could not be reached.
class RemoteError(Exception):
    pass


# A chat service the daemon dials out to. A room is a project's and a thread a
# cast's: both are made when first asked in, and found by name after that.
class Remote(Protocol):
    async def ask(self, *, room: str, thread: str, text: str) -> Posted: ...
    async def say(self, *, thread: str, text: str) -> None: ...

    # Stays connected until cancelled, handing `hear` whatever is written in a
    # thread. Raises `RemoteError` when the service will not have it.
    async def run(self, hear: Hear) -> None: ...


# What `[discord]` says, with the token read.
@dataclass(frozen=True, kw_only=True)
class DiscordSetup:
    token: str
    guild: int
    category: str
    allow: frozenset[int]
