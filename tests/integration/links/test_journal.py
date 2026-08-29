from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vekna.links.journal import Journal
from vekna.wire import CastGoodbye, CastHello, RiteDelta

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# A directory refuses to open for append whoever asks, where a read-only file
# still opens for a process running as root.
def _no_appends(log: Path) -> None:
    log.unlink()
    log.mkdir()


def _appends_again(log: Path) -> None:
    log.rmdir()
    log.touch()


def _hello(cast_id: str = "c1", *, started_at: datetime = _WHEN) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        ritual="fix_demo",
        components={"bound": 3},
        started_at=started_at,
    )


class TestRecording:
    @staticmethod
    def test_a_hello_opens_a_run_directory(tmp_path: Path):
        journal = Journal(tmp_path)

        journal.record(_hello())

        assert (tmp_path / "c1" / "run.json").is_file()
        assert (tmp_path / "c1" / "events.jsonl").is_file()

    @staticmethod
    def test_events_are_the_wire_verbatim(tmp_path: Path):
        journal = Journal(tmp_path)
        delta = RiteDelta(cast_id="c1", rite_id="r1", delta="one")

        journal.record(_hello())
        journal.record(delta)

        assert list(journal.events("c1")) == [_hello(), delta]

    @staticmethod
    def test_a_goodbye_closes_the_record(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())

        journal.record(CastGoodbye(cast_id="c1", status="disconnected", detail="eof"))

        record = journal.read("c1")
        assert record is not None
        assert record.status == "disconnected"
        assert record.detail == "eof"

    # The log now has a hole nothing in the log can show, so the record is where
    # it gets said. The raise goes on, because the daemon reports the failure.
    @staticmethod
    def test_an_append_that_fails_marks_the_run_gapped(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        _no_appends(tmp_path / "c1" / "events.jsonl")

        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))

        record = journal.read("c1")
        assert record is not None
        assert record.gapped

    @staticmethod
    def test_a_gap_survives_the_goodbye_that_closes_the_run(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        events = tmp_path / "c1" / "events.jsonl"
        _no_appends(events)
        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))
        _appends_again(events)

        with pytest.raises(OSError, match="log ends there"):
            journal.record(CastGoodbye(cast_id="c1", status="ok"))

        record = journal.read("c1")
        assert record is not None
        assert record.status == "ok"
        assert record.gapped

    # How the run ended is what the record says, and the append is not what
    # carries it. A cast that ended on a failed write and stayed `running` was
    # a row `prune` would never come back for.
    @staticmethod
    def test_a_goodbye_that_cannot_be_appended_still_closes_the_run(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        _no_appends(tmp_path / "c1" / "events.jsonl")

        with pytest.raises(IsADirectoryError):
            journal.record(CastGoodbye(cast_id="c1", status="ok"))

        journal.prune(keep=0)
        assert not list(tmp_path.iterdir())

    # A hole in the middle of the log is the one damage that reads as nothing,
    # and nothing reads the frames past it anyway: the ledger spends itself at
    # the first rite it cannot find. So the log ends at the gap whatever the
    # disk does afterwards, and what is left is a prefix of what the daemon saw.
    @staticmethod
    def test_a_gapped_log_never_appends_again(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        events = tmp_path / "c1" / "events.jsonl"
        _no_appends(events)
        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))
        _appends_again(events)

        with pytest.raises(OSError, match="log ends there"):
            journal.record(RiteDelta(cast_id="c1", rite_id="r2", delta="after"))

        assert not list(journal.events("c1"))

    # The record is what says the run lost something, so it is the one thing
    # that must survive the disk that lost it.
    @staticmethod
    def test_a_gap_that_cannot_be_written_keeps_the_record(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        _no_appends(tmp_path / "c1" / "events.jsonl")
        (tmp_path / "c1" / "run.part").mkdir()

        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))

        record = journal.read("c1")
        assert record is not None
        assert record.hello == _hello()

    # The disk that lost the event is the disk the gap marker is written to, so
    # both can fail at once, and the mark is owed until it lands. What the disk
    # coming back buys is that mark — not the log, which ended at the gap.
    @staticmethod
    def test_a_recovered_disk_marks_the_gap_and_no_more(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        events = tmp_path / "c1" / "events.jsonl"
        _no_appends(events)
        (tmp_path / "c1" / "run.part").mkdir()
        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))
        _appends_again(events)
        (tmp_path / "c1" / "run.part").rmdir()

        with pytest.raises(OSError, match="log ends there"):
            journal.record(RiteDelta(cast_id="c1", rite_id="r2", delta="after"))

        record = journal.read("c1")
        assert record is not None
        assert record.gapped
        assert not list(journal.events("c1"))

    # A record nothing can read back is one no resume accepts either, so there
    # is no gap left to mark and nothing left to retry. A write cut
    # mid-character is a `UnicodeDecodeError`, which is not the parser's.
    @staticmethod
    def test_a_torn_record_is_no_gap_left_to_mark(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        _no_appends(tmp_path / "c1" / "events.jsonl")
        (tmp_path / "c1" / "run.part").mkdir()
        with pytest.raises(IsADirectoryError):
            journal.record(RiteDelta(cast_id="c1", rite_id="r1", delta="lost"))
        (tmp_path / "c1" / "run.part").rmdir()
        # Cut mid-character, the way a daemon killed inside a write leaves it.
        (tmp_path / "c1" / "run.json").write_bytes(b'{"hello": {"cast_i\xff')

        with pytest.raises(OSError, match="log ends there"):
            journal.record(RiteDelta(cast_id="c1", rite_id="r2", delta="after"))

        assert journal.read("c1") is None

    # The first event is the one with no record behind it yet, so there is
    # nothing to mark and nothing to take away.
    @staticmethod
    def test_a_hello_that_cannot_be_written_leaves_nothing_behind(tmp_path: Path):
        journal = Journal(tmp_path)
        (tmp_path / "c1").write_text("where the run directory would go")

        with pytest.raises(FileExistsError):
            journal.record(_hello())

        assert journal.read("c1") is None

    # The record goes down before the log does, so a record that cannot be
    # written is a log that never starts. The other order left frames on disk
    # that `vekna log` never lists and a resume is told were never recorded.
    @staticmethod
    def test_a_hello_whose_record_fails_never_starts_the_log(tmp_path: Path):
        journal = Journal(tmp_path)
        (tmp_path / "c1").mkdir()
        (tmp_path / "c1" / "run.part").mkdir()

        with pytest.raises(IsADirectoryError):
            journal.record(_hello())

        assert not (tmp_path / "c1" / "events.jsonl").exists()

    @staticmethod
    def test_a_resumed_cast_records_what_it_carries_on_from(tmp_path: Path):
        journal = Journal(tmp_path)

        journal.record(_hello("c2").model_copy(update={"resumed_from": "c1"}))

        record = journal.read("c2")
        assert record is not None
        assert record.hello.resumed_from == "c1"


class TestReading:
    @staticmethod
    def test_an_unknown_cast_reads_as_nothing(tmp_path: Path):
        journal = Journal(tmp_path)

        assert journal.read("nope") is None
        assert not list(journal.events("nope"))

    @staticmethod
    def test_a_goodbye_for_a_cast_that_never_said_hello_closes_nothing(tmp_path: Path):
        journal = Journal(tmp_path)

        journal.record(CastGoodbye(cast_id="ghost", status="ok"))

        assert journal.read("ghost") is None

    @staticmethod
    def test_a_blank_line_in_the_log_is_not_an_event(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        with (tmp_path / "c1" / "events.jsonl").open("ab") as events:
            events.write(b"\n")

        assert list(journal.events("c1")) == [_hello()]

    @staticmethod
    def test_recent_is_newest_first_and_bounded(tmp_path: Path):
        journal = Journal(tmp_path)
        for index in range(3):
            journal.record(
                _hello(f"c{index}", started_at=_WHEN + timedelta(minutes=index))
            )

        recent = journal.recent(limit=2)

        assert [record.hello.cast_id for record in recent] == ["c2", "c1"]

    @staticmethod
    def test_recent_on_an_empty_root_is_empty(tmp_path: Path):
        assert Journal(tmp_path / "nothing-here").recent(limit=5) == []

    @staticmethod
    def test_a_stray_file_beside_the_runs_is_not_one(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello())
        (tmp_path / "notes.txt").write_text("mine")

        assert [record.hello.cast_id for record in journal.recent(limit=5)] == ["c1"]

    # What a daemon killed mid-write leaves behind, which is exactly when an
    # operator runs `vekna casts`.
    @staticmethod
    def test_a_torn_record_hides_neither_itself_nor_the_others(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        journal.record(_hello("c1", started_at=_WHEN + timedelta(minutes=1)))
        (tmp_path / "c1" / "run.json").write_text('{"hello": {"cast_i')

        assert journal.read("c1") is None
        assert [record.hello.cast_id for record in journal.recent(limit=5)] == ["c0"]

    # Cut mid-character the write comes back as a `UnicodeDecodeError`, out of
    # `read_text` and never past the parser, so the whole `ValueError` set is
    # what a reader has to hold — a listing must not end in a traceback.
    @staticmethod
    def test_a_record_cut_mid_character_hides_nothing_either(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        journal.record(CastGoodbye(cast_id="c0", status="ok"))
        journal.record(_hello("c1", started_at=_WHEN + timedelta(minutes=1)))
        (tmp_path / "c1" / "run.json").write_bytes(b'{"hello": {"cast_i\xff')

        assert journal.read("c1") is None
        assert [record.hello.cast_id for record in journal.recent(limit=5)] == ["c0"]
        journal.prune(keep=0)
        assert [path.name for path in tmp_path.iterdir()] == ["c1"]


class TestPruning:
    @staticmethod
    def test_only_the_newest_are_kept(tmp_path: Path):
        journal = Journal(tmp_path)
        for index in range(4):
            journal.record(
                _hello(f"c{index}", started_at=_WHEN + timedelta(minutes=index))
            )
            journal.record(CastGoodbye(cast_id=f"c{index}", status="ok"))

        journal.prune(keep=2)

        assert sorted(path.name for path in tmp_path.iterdir()) == ["c2", "c3"]

    @staticmethod
    def test_a_cast_still_running_is_left_alone(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("running"))
        journal.record(_hello("done", started_at=_WHEN + timedelta(minutes=1)))
        journal.record(CastGoodbye(cast_id="done", status="ok"))

        journal.prune(keep=0)

        assert [path.name for path in tmp_path.iterdir()] == ["running"]
