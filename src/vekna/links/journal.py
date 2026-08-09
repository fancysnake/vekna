import os
from collections.abc import Iterator
from pathlib import Path

from vekna.pacts.casts import RunRecord
from vekna.wire import (
    CastGoodbye,
    CastHello,
    SurfaceHello,
    WireMessage,
    decode_frame,
    encode_frame,
)

_EVENTS = "events.jsonl"
_RUN = "run.json"
_RUNS_ENV = "VEKNA_RUNS"


# `~/.config/vekna/runs` is the namespace 00-common fixes; the variable is what
# lets a test — and a second user on one machine — keep their own.
def default_runs_root() -> Path:
    if (named := os.environ.get(_RUNS_ENV)) is not None:
        return Path(named)
    return Path.home() / ".config" / "vekna" / "runs"


# Everything the daemon saw, on disk, keyed by cast. `run.json` is the index —
# what the cast was and how it ended — and `events.jsonl` is the wire verbatim,
# which is what makes resume possible and what `hand/05-replay.md` will read.
# ponytail: one open per event. A handle per live cast is the upgrade if a
# streaming cast ever makes this show up in a profile.
class Journal:
    def __init__(self, root: Path) -> None:
        self._root = root

    def record(self, message: WireMessage) -> None:
        if isinstance(message, SurfaceHello):
            return
        directory = self._root / message.cast_id
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / _EVENTS).open("ab") as events:
            events.write(encode_frame(message))
        if isinstance(message, CastHello):
            self._write(RunRecord(hello=message))
        elif isinstance(message, CastGoodbye):
            self._close(message)

    def read(self, cast_id: str) -> RunRecord | None:
        path = self._root / cast_id / _RUN
        if not path.is_file():
            return None
        return RunRecord.model_validate_json(path.read_text())

    def events(self, cast_id: str) -> Iterator[WireMessage]:
        path = self._root / cast_id / _EVENTS
        if not path.is_file():
            return
        with path.open("rb") as events:
            for frame in events:
                if frame.strip():
                    yield decode_frame(frame)

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
        path = self._root / record.hello.cast_id / _RUN
        path.write_text(record.model_dump_json(indent=2))

    # A goodbye for a cast whose hello never landed leaves nothing to close —
    # the daemon would have dropped it, so this is only reachable by a journal
    # written by hand.
    def _close(self, goodbye: CastGoodbye) -> None:
        if (record := self.read(goodbye.cast_id)) is None:
            return
        self._write(
            RunRecord(hello=record.hello, status=goodbye.status, detail=goodbye.detail)
        )
