import contextlib
import shutil
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
# which is what makes resume possible and what `docs/hand/replay.md` will read.
# Where those two live, and how they are read back, is `vekna.wire`'s: a resumed
# cast reads the same files from a process that shares nothing else with this.
# ponytail: one open per event. A handle per live cast is the upgrade if a
# streaming cast ever makes this show up in a profile.
class Journal:
    def __init__(self, root: Path) -> None:
        self._root = root
        # The casts whose log lost an event, and of those, the ones whose record
        # has not admitted it yet. In memory because they only have to outlive
        # the failure: a daemon that dies here leaves a log that is short, which
        # is what a killed cast leaves too.
        self._gapped: set[str] = set()
        self._unmarked: set[str] = set()

    def record(self, message: CastMessage) -> None:
        # The record is written before the log grows, because a record that
        # never landed is a log nothing can find: `vekna log` does not list it,
        # `prune` never collects it, and a resume is told the daemon never saw
        # the cast. The other order — record on disk, log short — is what every
        # interrupted cast leaves, and a resume knows what to do with it.
        if isinstance(message, CastHello):
            self._write(RunRecord(hello=message))
        try:
            self._append_unless_gapped(message)
        finally:
            # A goodbye's status is record-only information, like the gap mark,
            # so it lands whether or not the log took the frame. Inside the
            # append, a cast that ended on a failed write stayed `running`
            # forever, and `prune` collects nothing that is still running.
            if isinstance(message, CastGoodbye):
                self._close(message)

    # Once a log is behind it stays behind. An append that failed leaves the log
    # short, and a short log is what every interrupted cast leaves — a resume
    # replays what landed and runs live from there. A hole in the middle is the
    # one damage that reads as nothing, and the frames past it are unreachable
    # anyway: the ledger spends itself at the first rite it cannot find. So the
    # tail is forfeit from the failure on, `events.jsonl` stays a prefix of what
    # the daemon saw, and every frame dropped after it is still raised about,
    # because every one of them really is dropped.
    def _append_unless_gapped(self, message: CastMessage) -> None:
        if (cast_id := message.cast_id) in self._gapped:
            self._mark(cast_id)
            msg = f"cast {cast_id} lost an event and its log ends there"
            raise OSError(msg)
        try:
            self._append(message)
        except OSError:
            self._gapped.add(cast_id)
            self._unmarked.add(cast_id)
            # Tried here as well as before the next event, because there may be
            # no next event: a cast that ends on this failure still has a
            # record, and `vekna log` still gets to be right about it.
            self._mark(cast_id)
            raise

    def _append(self, message: CastMessage) -> None:
        log = events_log(self._root, message.cast_id)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("ab") as events:
            events.write(encode_frame(message))

    # Read back and written on rather than rebuilt field by field: what this
    # hands over is parsed fresh off the disk each time, so it is nobody else's
    # to hold, and a field added to `RunRecord` needs nothing said here.
    # The disk that lost the event is the disk this is written to, so it can
    # refuse too — and then the cast stays owed and the next event tries again.
    def _mark(self, cast_id: str) -> None:
        if cast_id not in self._unmarked:
            return
        with contextlib.suppress(OSError):
            if (record := self._parsed(cast_id)) is not None:
                record.gapped = True
                self._write(record)
            self._unmarked.discard(cast_id)

    # `read` answers a disk that will not talk with `None`, which would read
    # here as "nothing to mark" and settle a debt the disk never let this pay.
    # A record that is torn, or that was never written, is one no resume accepts
    # either: nothing left to mark, and the retry stops.
    def _parsed(self, cast_id: str) -> RunRecord | None:
        try:
            return read_record(self._root, cast_id)
        except ValueError:
            return None

    # A record that will not parse is one the daemon was killed halfway through
    # writing. Skipped rather than raised, because the command that reads these
    # is what an operator runs after a daemon died: one torn file must not be
    # able to hide every healthy cast behind a traceback. `ValueError` rather
    # than `ValidationError`, because a write cut mid-character comes back out
    # of `read_text` as a `UnicodeDecodeError`, before the parser sees it.
    def read(self, cast_id: str) -> RunRecord | None:
        try:
            return read_record(self._root, cast_id)
        except (OSError, ValueError):
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
        path.parent.mkdir(parents=True, exist_ok=True)
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
