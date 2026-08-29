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
# which is what makes resume possible and what `docs/hand/replay.md` will read.
# Where those two live, and how they are read back, is `vekna.wire`'s: a resumed
# cast reads the same files from a process that shares nothing else with this.
# ponytail: one open per event. A handle per live cast is the upgrade if a
# streaming cast ever makes this show up in a profile.
class Journal:
    def __init__(self, root: Path) -> None:
        self._root = root
        # The casts whose log is ahead of what their record admits. In memory
        # because it only has to outlive the failure: a daemon that dies here
        # leaves a log that is short, which is what a killed cast leaves too.
        self._behind: set[str] = set()

    def record(self, message: CastMessage) -> None:
        # An append that failed leaves the log short, and a short log is what
        # every interrupted cast leaves — a resume replays what landed and runs
        # live from there. Appending past it is the one damage that reads as
        # nothing: a hole in the middle, over a record that says all is well.
        # So the record admits the gap before the log grows again, and if it
        # cannot, this raises and the daemon drops the event instead.
        self._settle(message.cast_id)
        try:
            self._append(message)
        except OSError:
            self._behind.add(message.cast_id)
            # Tried here as well as before the next event, because there may be
            # no next event: a cast that ends on this failure still has a
            # record, and `vekna log` still gets to be right about it.
            with contextlib.suppress(OSError):
                self._settle(message.cast_id)
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

    # Read back and written on rather than rebuilt field by field: what this
    # hands over is parsed fresh off the disk each time, so it is nobody else's
    # to hold, and a field added to `RunRecord` needs nothing said here.
    # `read_record` rather than `read`, which answers a disk that will not talk
    # with `None`: that would read here as "nothing to mark" and let the next
    # append through. The `OSError` let out instead is what refuses it.
    # A record that is torn, or that was never written, is one no resume
    # accepts either — there is nothing to mark and nothing left to protect,
    # so the log may go on growing. `ValueError` rather than `ValidationError`
    # because a write cut mid-character is a `UnicodeDecodeError`, and this
    # wants the whole set `read_run` already refuses.
    def _settle(self, cast_id: str) -> None:
        if cast_id not in self._behind:
            return
        try:
            record = read_record(self._root, cast_id)
        except ValueError:
            record = None
        if record is not None:
            record.gapped = True
            self._write(record)
        self._behind.discard(cast_id)

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
