from dataclasses import dataclass

from pydantic import JsonValue

from vekna.lexicon._pacts import Resumption
from vekna.wire import RiteFinished, RiteStarted

_MEDIUM = "medium"


@dataclass(frozen=True, kw_only=True)
class _Entry:
    name: str
    result: JsonValue


# What an interrupted cast already did, keyed by the rite that did it. Only
# medium rites are in here. A step returns a `Transition`, whose target is
# a function reference no journal can hold, so a resumed cast re-runs its steps
# — cheap, and the same walk it took before — while every agent call, shell
# command and prompt inside them comes back off the record instead of happening
# twice.
# ponytail: the match is `rite_id` and name, and the first miss spends the whole
# ledger. Rite ids are a counter, so they line up only while the resumed cast
# walks the path the recorded one walked; a ritual that branches differently
# stops replaying at the point it diverged and runs live from there, which is
# the safe way to be wrong.
class Ledger:
    def __init__(self, entries: dict[str, _Entry]) -> None:
        self._entries = entries
        self._spent = False

    @classmethod
    def from_resumption(cls, resumption: Resumption) -> "Ledger":
        names = {
            event.rite_id: event.name
            for event in resumption.events
            if isinstance(event, RiteStarted) and event.category == _MEDIUM
        }
        # A rite that finished having recorded nothing is not held here at all.
        # `take` answers "nothing recorded" and "recorded a null" with the same
        # `None`, so keeping it would let a rite run a second time while the
        # ledger stayed unspent — the one thing replay is for. Left out, it is
        # a miss like any other: the resume runs live from that rite on.
        entries = {
            event.rite_id: _Entry(name=names[event.rite_id], result=event.result)
            for event in resumption.events
            if isinstance(event, RiteFinished)
            and event.status == "ok"
            and event.result is not None
            and event.rite_id in names
        }
        return cls(entries)

    def take(self, *, rite_id: str, name: str) -> JsonValue | None:
        if self._spent:
            return None
        entry = self._entries.get(rite_id)
        if entry is None or entry.name != name:
            self._spent = True
            return None
        return entry.result
