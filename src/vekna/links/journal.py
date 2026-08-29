import contextlib
import shutil
from collections.abc import Iterator
from pathlib import Path

from pydantic import ValidationError

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
# which is what makes resume possible and what issue #114 will read.
# Where those two live, and how they are read back, is `vekna.wire`'s: a resumed
# cast reads the same files from a process that shares nothing else with this.
# ponytail: one open per event. A handle per live cast is the upgrade if a
# streaming cast ever makes this show up in a profile.
class Journal:
    def __init__(self, root: Path) -> None:
        self._root = root

    def record(self, message: CastMessage) -> None:
        try:
            self._append(message)
        except OSError:
            # Marked before the caller hears about it, because what is on disk
            # is now a log with a hole in it and nothing in the log says so.
            # The raise still goes on, so the daemon reports the failure rather
            # than swallowing it here.
            self._mark_gapped(message.cast_id)
            raise
        if isinstance(message, CastHello):
            self._write(RunRecord(hello=message))
        elif isinstance(message, CastGoodbye):
            self._close(message)

    def _append(self, message: CastMessage) -> None:
        log = events_log(self._root, message.cast_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as events:
            events.write(encode_frame(message))

    # Read back and written on rather than rebuilt field by field: what `read`
    # hands over is parsed fresh off the disk each time, so it is nobody else's
    # to hold, and a field added to `RunRecord` needs nothing said here.
    # The write that would record the gap is the same kind of write that just
    # failed, so it can fail too — and a record that survives ungapped over a
    # log with a hole in it is worse than no record at all, because that is the
    # one `vekna cast --continue` accepts. The record goes instead: unlinking is
    # the one thing a disk with no room left still does, and what a resume then
    # finds is nothing to resume from, said in a sentence.
    def _mark_gapped(self, cast_id: str) -> None:
        try:
            if (record := self.read(cast_id)) is not None:
                record.gapped = True
                self._write(record)
        except OSError:
            with contextlib.suppress(OSError):
                run_file(self._root, cast_id).unlink(missing_ok=True)

    # A record that will not parse is one the daemon was killed halfway through
    # writing. Skipped rather than raised, because the command that reads these
    # is what an operator runs after a daemon died: one torn file must not be
    # able to hide every healthy cast behind a traceback.
    def read(self, cast_id: str) -> RunRecord | None:
        try:
            return read_record(self._root, cast_id)
        except (OSError, ValidationError):
            return None

    # Every surface prints a cast id cut to eight characters, so eight is what
    # an operator has back to type. A prefix that names one cast is that cast;
    # one that names several is not an id yet, and the caller says so.
    def matching(self, prefix: str) -> list[str]:
        if not prefix or not self._root.is_dir():
            return []
        return sorted(
            found.name
            for found in self._root.iterdir()
            if found.is_dir() and found.name.startswith(prefix)
        )

    def events(self, cast_id: str) -> Iterator[WireMessage]:
        return read_events(self._root, cast_id)

    # Newest first, by when the cast started rather than by when its directory
    # was written: a resumed cast and the one it resumed sit next to each other
    # in the order they were run.
    def recent(self, *, limit: int) -> list[RunRecord]:
        return self._newest_first()[:limit]

    # Nothing else ever removes a cast, so without this the runs root grows for
    # as long as the machine lives and every `vekna log` pays for all of it.
    # A cast still running is left alone whatever its age, and so is a record
    # this cannot read: deleting what it could not read back is not its call.
    def prune(self, *, keep: int) -> None:
        for record in self._newest_first()[keep:]:
            if record.status != "running":
                shutil.rmtree(
                    run_file(self._root, record.hello.cast_id).parent,
                    ignore_errors=True,
                )

    def _newest_first(self) -> list[RunRecord]:
        found = [record for record in self._all() if record is not None]
        found.sort(key=lambda record: record.hello.started_at, reverse=True)
        return found

    def _all(self) -> Iterator[RunRecord | None]:
        if not self._root.is_dir():
            return
        for directory in self._root.iterdir():
            if directory.is_dir():
                yield self.read(directory.name)

    # Written beside itself and moved into place, because a plain write
    # truncates first: a daemon killed between the two leaves half a record
    # where `vekna log` and `vekna cast --continue` both look. `os.replace` is
    # atomic within a directory, so what is there is either the last record or
    # this one.
    def _write(self, record: RunRecord) -> None:
        path = run_file(self._root, record.hello.cast_id)
        half = path.with_suffix(".part")
        half.write_text(record.model_dump_json(indent=2))
        half.replace(path)

    # A goodbye for a cast whose hello never landed leaves nothing to close —
    # the daemon would have dropped it, so this is only reachable by a journal
    # written by hand.
    def _close(self, goodbye: CastGoodbye) -> None:
        if (record := self.read(goodbye.cast_id)) is None:
            return
        record.status = goodbye.status
        record.detail = goodbye.detail
        self._write(record)
