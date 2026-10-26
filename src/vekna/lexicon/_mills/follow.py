from vekna.lexicon._pacts import LineageProtocol
from vekna.wire import CastGoodbye, CastHello, WireMessage


# The casts a cast typed by hand set going — the ones it queued, the ones those
# queued, and so on — read off what the daemon tells every surface: a hello
# names the cast that queued it, and a goodbye says how it went. A cast this one
# queued is expected from the moment the daemon took it, because the daemon's
# word to this cast and its fan-out to surfaces travel on two connections, and
# the second may still be on its way when the first lands.
class Lineage(LineageProtocol):
    def __init__(self, root: str) -> None:
        self._root = root
        self._parents: dict[str, str | None] = {}
        self._ended: dict[str, bool] = {}
        self._expected: set[str] = set()

    def expect(self, cast_id: str) -> None:
        self._expected.add(cast_id)

    def heard(self, message: WireMessage) -> None:
        if isinstance(message, CastHello):
            self._parents[message.cast_id] = message.enqueued_by
        elif isinstance(message, CastGoodbye) and self.descends(message.cast_id):
            self._ended[message.cast_id] = message.status == "ok"

    # Walked up through the parents rather than remembered at the hello, so a
    # chain heard out of order still resolves; no chain is longer than the casts
    # in it, which is what bounds a loop a peer could have sent.
    def descends(self, cast_id: str) -> bool:
        parent = self._parents.get(cast_id)
        for _ in self._parents:
            if parent is None:
                return False
            if parent == self._root:
                return True
            parent = self._parents.get(parent)
        return False

    @property
    def settled(self) -> bool:
        return self._expected <= self._parents.keys() and all(
            cast_id in self._ended
            for cast_id in self._parents
            if self.descends(cast_id)
        )

    @property
    def failed(self) -> bool:
        return not all(self._ended.values())
