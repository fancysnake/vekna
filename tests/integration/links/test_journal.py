import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from vekna.links.journal import Journal
from vekna.pacts.casts import DamagedRun, Run
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


def _ids(runs: list[Run]) -> list[str]:
    return [
        run.cast_id if isinstance(run, DamagedRun) else run.hello.cast_id
        for run in runs
    ]


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
    # operator runs `vekna log`: the torn one is a row too, with the id and the
    # directory's time being all that is left of it, and it sorts by that time.
    @staticmethod
    def test_a_torn_record_is_listed_as_damaged_beside_the_others(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        journal.record(_hello("c1", started_at=_WHEN + timedelta(minutes=1)))
        (tmp_path / "c1" / "run.json").write_text('{"hello": {"cast_i')

        recent = journal.recent(limit=5)

        assert journal.read("c1") is None
        assert _ids(recent) == ["c1", "c0"]
        assert isinstance(recent[0], DamagedRun)
        assert recent[0].seen_at > _WHEN

    # Cut mid-character the write comes back as a `UnicodeDecodeError`, out of
    # `read_text` and never past the parser, so the whole `ValueError` set is
    # what a reader has to hold — a listing must not end in a traceback. And
    # nothing resumes a run like this, so `prune` collects it like a finished
    # one rather than leaving it for as long as the machine lives.
    @staticmethod
    def test_a_record_cut_mid_character_is_listed_and_collected(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        journal.record(CastGoodbye(cast_id="c0", status="ok"))
        journal.record(_hello("c1", started_at=_WHEN + timedelta(minutes=1)))
        (tmp_path / "c1" / "run.json").write_bytes(b'{"hello": {"cast_i\xff')

        assert journal.read("c1") is None
        assert _ids(journal.recent(limit=5)) == ["c1", "c0"]
        journal.prune(keep=0)
        assert not list(tmp_path.iterdir())

    # A hello that got as far as the directory and no further: no record to
    # read, and before this nothing listed it and nothing collected it.
    @staticmethod
    def test_an_empty_run_directory_is_damaged(tmp_path: Path):
        journal = Journal(tmp_path)
        (tmp_path / "c1").mkdir()

        recent = journal.recent(limit=5)

        assert _ids(recent) == ["c1"]
        assert isinstance(recent[0], DamagedRun)
        journal.prune(keep=0)
        assert not list(tmp_path.iterdir())

    # A `started_at` with no zone, which the field's type accepts and a hand
    # written or foreign `run.json` can carry, against the damaged row's time,
    # which always has one: the sort raised, and `vekna log` and the startup
    # prune died over a run they were both meant to be listing. Read as UTC and
    # the record stays a record — nothing here makes it damaged, because `prune`
    # collects damaged runs and this one resumes.
    @staticmethod
    def test_a_record_with_no_zone_sorts_against_a_damaged_run(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0", started_at=_WHEN.replace(tzinfo=None)))
        (tmp_path / "c1").mkdir()

        recent = journal.recent(limit=5)

        assert _ids(recent) == ["c1", "c0"]
        assert not isinstance(recent[1], DamagedRun)

    # Another daemon's prune, or an operator's `rm`, between the listing and the
    # stat of what it named: nothing left to read and nothing left to date it by,
    # and a listing must not end in a traceback over a run that is gone.
    @staticmethod
    def test_a_directory_that_goes_mid_listing_is_skipped(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        (tmp_path / "gone").mkdir()
        real_stat = Path.stat

        def stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            if path.name == "gone":
                raise FileNotFoundError(2, "No such file or directory")
            return real_stat(path, follow_symlinks=follow_symlinks)

        monkeypatch.setattr(Path, "stat", stat)

        assert _ids(journal.recent(limit=5)) == ["c0"]


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

    # Counted against `keep` like any other run: the newest damaged directory
    # is what the operator is about to look at, and the finished cast behind
    # it is the one past the line.
    @staticmethod
    def test_a_damaged_run_counts_against_keep(tmp_path: Path):
        journal = Journal(tmp_path)
        journal.record(_hello("c0"))
        journal.record(CastGoodbye(cast_id="c0", status="ok"))
        (tmp_path / "c1").mkdir()

        journal.prune(keep=1)

        assert [path.name for path in tmp_path.iterdir()] == ["c1"]

    @staticmethod
    def test_a_directory_that_will_not_go_is_named_and_the_rest_still_go(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        journal = Journal(tmp_path)
        for cast_id in ("stuck", "loose"):
            journal.record(_hello(cast_id))
            journal.record(CastGoodbye(cast_id=cast_id, status="ok"))
        real_rmtree = shutil.rmtree

        def rmtree(path: Path, **kwargs: object) -> None:
            if path.name == "stuck":
                if kwargs.get("ignore_errors"):
                    return
                raise PermissionError(13, "Permission denied")
            real_rmtree(path)

        monkeypatch.setattr(shutil, "rmtree", rmtree)

        failed = journal.prune(keep=0)

        assert [path.name for path in tmp_path.iterdir()] == ["stuck"]
        assert failed == [f"{tmp_path / 'stuck'}: [Errno 13] Permission denied"]

    # The sweep after the first failure is what takes a partly-removed cast,
    # and an operator told a directory could not be pruned goes looking for one
    # that is no longer there.
    @staticmethod
    def test_a_directory_the_sweep_takes_is_not_reported(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        journal = Journal(tmp_path)
        journal.record(_hello("half"))
        journal.record(CastGoodbye(cast_id="half", status="ok"))
        real_rmtree = shutil.rmtree

        def rmtree(path: Path, **kwargs: object) -> None:
            if not kwargs.get("ignore_errors"):
                (path / "run.json").unlink()
                raise PermissionError(13, "Permission denied")
            real_rmtree(path)

        monkeypatch.setattr(shutil, "rmtree", rmtree)

        failed = journal.prune(keep=0)

        assert not list(tmp_path.iterdir())
        assert not failed

    # A directory the daemon cannot stat is not a directory that went, and
    # prune runs while a daemon is starting: neither a raise nor a dropped
    # report is an answer an operator can act on.
    @staticmethod
    def test_a_directory_whose_absence_cannot_be_confirmed_is_reported(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        journal = Journal(tmp_path)
        journal.record(_hello("stuck"))
        journal.record(CastGoodbye(cast_id="stuck", status="ok"))
        statted: list[Path] = []

        def rmtree(_path: Path, **kwargs: object) -> None:
            if not kwargs.get("ignore_errors"):
                raise PermissionError(13, "Permission denied")

        # The way a permission change between the removal and the check leaves
        # the directory unstattable — for root as much as for anyone else.
        def lstat(path: Path) -> os.stat_result:
            statted.append(path)
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(shutil, "rmtree", rmtree)
        monkeypatch.setattr(os, "lstat", lstat)

        failed = journal.prune(keep=0)

        assert statted == [tmp_path / "stuck"]
        assert failed == [f"{tmp_path / 'stuck'}: [Errno 13] Permission denied"]
