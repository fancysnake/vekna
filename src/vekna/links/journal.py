from collections.abc import Iterator
from pathlib import Path

from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    RunRecord,
    WireMessage,
    encode_frame,
    events_log,
    read_events,
    read_record,
    run_file,
)


# Everything the daemon saw, on disk, keyed by cast. `run.json` is the index —
# what the cast was and how it ended — and `events.jsonl` is the wire verbatim,
# which is what makes resume possible and what `hand/05-replay.md` will read.
# Where those two live, and how they are read back, is `vekna.wire`'s: a resumed
# cast reads the same files from a process that shares nothing else with this.
# ponytail: one open per event. A handle per live cast is the upgrade if a
# streaming cast ever makes this show up in a profile.
class Journal:
    def __init__(self, root: Path) -> None:
        self._root = root

    def record(self, message: CastMessage) -> None:
        log = events_log(self._root, message.cast_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as events:
            events.write(encode_frame(message))
        if isinstance(message, CastHello):
            self._write(RunRecord(hello=message))
        elif isinstance(message, CastGoodbye):
            self._close(message)

    def read(self, cast_id: str) -> RunRecord | None:
        return read_record(self._root, cast_id)

    def events(self, cast_id: str) -> Iterator[WireMessage]:
        return read_events(self._root, cast_id)

    # Newest first, by when the cast started rather than by when its directory
    # was written: a resumed cast and the one it resumed sit next to each other
    # in the order they were run.
    def recent(self, *, limit: int) -> list[RunRecord]:
        found = [record for record in self._all() if record is not None]
        found.sort(key=lambda record: record.hello.started_at, reverse=True)
        return found[:limit]

    def _all(self) -> Iterator[RunRecord | None]:
        if not self._root.is_dir():
            return
        for directory in self._root.iterdir():
            if directory.is_dir():
                yield self.read(directory.name)

    def _write(self, record: RunRecord) -> None:
        run_file(self._root, record.hello.cast_id).write_text(
            record.model_dump_json(indent=2)
        )

    # A goodbye for a cast whose hello never landed leaves nothing to close —
    # the daemon would have dropped it, so this is only reachable by a journal
    # written by hand.
    def _close(self, goodbye: CastGoodbye) -> None:
        if (record := self.read(goodbye.cast_id)) is None:
            return
        self._write(
            RunRecord(hello=record.hello, status=goodbye.status, detail=goodbye.detail)
        )
