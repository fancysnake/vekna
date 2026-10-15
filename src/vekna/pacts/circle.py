from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from vekna.wire import CastHello

# What a project's circle allows when nothing says otherwise.
DEFAULT_PROCESSES = 4


# Read each time they are asked for, so an edited config counts from the next
# cast on without restarting the daemon. `processes` is per project, found from
# the tree the cast runs in; `coding` is per account, so only the user's own
# config says it, and `None` is no limit.
class Limits(Protocol):
    def processes(self, project_root: str) -> int: ...
    def coding(self) -> int | None: ...


# How a spawned cast process ended, and the last thing it said: a cast that dies
# before its hello — a ritual that is not there, a component that will not
# validate — has nothing on the wire, so this is all there is to say why.
@dataclass(frozen=True, kw_only=True)
class Exited:
    code: int | None
    said: str


Spawn = Callable[[CastHello], Awaitable[Exited]]
