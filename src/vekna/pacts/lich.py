from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from vekna.wire import LichRose, LichStatus, RunRecord, WireMessage


# A lich's whole durable self. Anything larger — a session log, the casts it has
# run — is the journal's already: "what did hollow-vesper cast" is a query over
# `runs/` filtered by lich, which costs one field on the cast record and no
# bookkeeping at all. No pid, because a pid restates what the lich's open socket
# says and does so staler.
# Keyed by name, not by root: a project may hold several liches, so the name is
# the only thing that identifies one. The process is not the lich; the row is.
class Phylactery(BaseModel):
    name: str
    root: str
    created: datetime
    # The last cast this lich started, and the channel it speaks in. Both None
    # until there is one — a lich that has cast nothing is still a lich.
    last_cast: str | None = None
    channel: str | None = None


# What the mills hold instead of a file. `links` and `mills` are peers here, so
# the registry a mill reasons about arrives through this and the binding is
# `inits`' job.
class Registry(Protocol):
    def rows(self) -> list[Phylactery]: ...

    # By name, which is the key: a lich rising again is the same row updated,
    # not a second one beside it.
    def save(self, row: Phylactery) -> None: ...

    def drop(self, name: str) -> None: ...


# A lich's open connection, which is the only place a command for it can go.
# Spelled here rather than reusing the surface's `Surface`: `pacts` modules are
# independent of each other, and one sentence of duplication is what that costs.
class Station(Protocol):
    def send(self, message: WireMessage) -> None: ...


# A lich the daemon can currently reach: how it rose, what it last said about
# itself, and the connection to say things back down. Liveness is this object
# existing — nothing stores it, because the socket already knows.
@dataclass
class LichView:
    rose: LichRose
    station: Station
    said: LichStatus | None = None


# One lich as a surface shows it: the row it is, whether the daemon can reach it
# this second, what it said it was doing, and the cast it last started — read
# out of the journal, which is where a lich's history already lives.
@dataclass(frozen=True, kw_only=True)
class LichLine:
    row: Phylactery
    live: bool
    said: LichStatus | None = None
    last: RunRecord | None = None


# The registry is every lich at once, so a file that will not parse is not one
# row lost the way a torn `run.json` is — it is all of them. Read as empty it
# would hand out a name somebody already holds and raise a second lich onto a
# live one's channel, so it is said instead, naming the file.
class RegistryUnreadableError(Exception):
    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"{path} will not parse — {detail}")
        self.path = path
