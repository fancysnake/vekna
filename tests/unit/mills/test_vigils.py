import logging
from datetime import UTC, datetime, timedelta

import pytest

from vekna.mills.vigils import Vigils
from vekna.pacts.casts import Casts, CastView
from vekna.pacts.circle import CastQueue, Limits, Vigil
from vekna.wire import CastHello, CastStatus, RunRecord

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_HOUR = 3600
_LIVE_PID = 41
_DEAD_PID = 42
_PROJECTS = {"/app": "/app/.git", "/api": "/api/.git"}


class _Limits(Limits):
    def __init__(self, vigils: int = 9) -> None:
        self._vigils = vigils

    def processes(self, project_root: str) -> int:
        raise NotImplementedError

    def worktrees(self, project_root: str) -> int:
        raise NotImplementedError

    def prepare(self, project_root: str) -> str | None:
        raise NotImplementedError

    def base(self, project_root: str) -> str | None:
        raise NotImplementedError

    def coding(self) -> int | None:
        raise NotImplementedError

    def total(self) -> int:
        raise NotImplementedError

    def vigils(self) -> int:
        return self._vigils


# The hub and the circle in one: what is enqueued is a queued cast from then
# on. `full` names the project roots with no spare room.
class _Board(Casts, CastQueue):
    def __init__(self, *full: str) -> None:
        self._casts: dict[str, CastView] = {}
        self.full = set(full)
        self.asked: list[tuple[str, str]] = []
        self.enqueued: list[CastHello] = []

    @property
    def casts(self) -> dict[str, CastView]:
        return self._casts

    def has_spare(self, *, project_root: str, project: str) -> bool:
        self.asked.append((project_root, project))
        return project_root not in self.full

    def enqueue(self, hello: CastHello) -> None:
        self.enqueued.append(hello)
        self.seen(hello, "queued")

    def seen(self, hello: CastHello, status: CastStatus) -> None:
        self._casts[hello.cast_id] = CastView(hello=hello, status=status)


def _vigil(
    name: str = "prwatch", *, root: str = "/app", ritual: str = "heal", every: int = 60
) -> Vigil:
    return Vigil(
        name=name,
        project_root=root,
        ritual=ritual,
        every=every,
        args={"author": "me", "max_prs": 3},
    )


def _hello(
    cast_id: str,
    *,
    ago: int = 0,
    ritual: str = "heal",
    vigil: str | None = None,
    pid: int | None = None,
) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/app",
        project=_PROJECTS["/app"],
        ritual=ritual,
        components={},
        started_at=_NOW - timedelta(seconds=ago),
        vigil=vigil,
        pid=pid,
    )


def _record(hello: CastHello, status: CastStatus = "ok") -> RunRecord:
    return RunRecord(hello=hello, status=status)


def _vigils(board: _Board, limits: _Limits | None = None) -> Vigils:
    return Vigils(
        hub=board,
        queue=board,
        limits=limits or _Limits(),
        alive=lambda pid: pid == _LIVE_PID,
    )


def _tick(
    vigils: Vigils, *watched: Vigil, records: tuple[RunRecord, ...] = ()
) -> list[str]:
    started = vigils.tick(now=_NOW, vigils=watched, projects=_PROJECTS, records=records)
    return [f"{hello.vigil} {hello.project_root}" for hello in started]


class TestDue:
    @staticmethod
    def test_a_vigil_that_never_ran_is_cast_at_once(caplog: pytest.LogCaptureFixture):
        caplog.set_level(logging.INFO)
        board = _Board()

        started = _vigils(board).tick(
            now=_NOW, vigils=[_vigil()], projects=_PROJECTS, records=[]
        )

        hello = started[0]
        assert board.enqueued == started
        assert board.asked == [("/app", "/app/.git")]
        assert started == [
            CastHello(
                cast_id=hello.cast_id,
                project_root="/app",
                project="/app/.git",
                ritual="heal",
                components={"author": "me", "max_prs": 3},
                started_at=_NOW,
                wired=True,
                vigil="prwatch",
            )
        ]
        assert [record.getMessage() for record in caplog.records] == [
            f"vigil prwatch cast heal {hello.cast_id} in /app"
        ]

    @staticmethod
    def test_it_waits_out_the_interval_since_the_last_cast_whoever_started_it():
        board = _Board()
        by_hand = _record(_hello("c1", ago=59))

        assert _tick(_vigils(board), _vigil(every=60), records=(by_hand,)) == []
        assert not board.asked

    @staticmethod
    def test_it_is_due_the_second_the_interval_has_passed():
        board = _Board()
        records = (_record(_hello("c1", ago=60)), _record(_hello("c0", ago=_HOUR)))

        assert _tick(_vigils(board), _vigil(every=60), records=records) == [
            "prwatch /app"
        ]

    @staticmethod
    def test_a_cast_of_another_ritual_or_project_does_not_count():
        board = _Board()
        records = (
            _record(_hello("c1", ritual="sweep")),
            _record(
                _hello("c2").model_copy(
                    update={"project_root": "/api", "project": "/api/.git"}
                )
            ),
        )

        assert _tick(_vigils(board), _vigil(), records=records) == ["prwatch /app"]

    @staticmethod
    def test_the_last_cast_is_read_off_the_hub_too():
        board = _Board()
        board.seen(_hello("c1", ago=10), "ok")

        assert _tick(_vigils(board), _vigil(every=60)) == []


class TestOneAtATime:
    @staticmethod
    @pytest.mark.parametrize("status", ["queued", "running"])
    def test_a_cast_of_the_ritual_open_in_the_project_holds_the_vigil(
        status: CastStatus,
    ):
        board = _Board()
        board.seen(_hello("c1", ago=_HOUR), status)

        assert _tick(_vigils(board), _vigil(), _vigil(root="/api")) == ["prwatch /api"]
        assert board.asked == [("/api", "/api/.git")]

    @staticmethod
    def test_a_cast_left_running_by_a_stopped_daemon_holds_it_while_its_process_lives():
        board = _Board()
        left = _record(_hello("c1", ago=_HOUR, pid=_LIVE_PID), "running")

        assert _tick(_vigils(board), _vigil(), records=(left,)) == []

    @staticmethod
    @pytest.mark.parametrize("pid", [_DEAD_PID, None])
    def test_a_record_left_running_with_no_process_does_not(pid: int | None):
        board = _Board()
        left = _record(_hello("c1", ago=_HOUR, pid=pid), "running")

        assert _tick(_vigils(board), _vigil(), records=(left,)) == ["prwatch /app"]

    @staticmethod
    def test_the_hub_s_word_on_a_cast_wins_over_its_record():
        board = _Board()
        hello = _hello("c1", ago=_HOUR, pid=_LIVE_PID)
        board.seen(hello, "ok")

        assert _tick(
            _vigils(board), _vigil(), records=(_record(hello, "running"),)
        ) == ["prwatch /app"]

    @staticmethod
    def test_two_vigils_of_one_ritual_in_one_project_cast_it_once():
        board = _Board()

        assert _tick(_vigils(board), _vigil("first"), _vigil("second")) == [
            "first /app"
        ]


class TestRoom:
    @staticmethod
    def test_a_project_with_no_spare_room_is_passed_over_and_stays_due():
        board = _Board("/app")
        vigils = _vigils(board)

        assert _tick(vigils, _vigil(), _vigil(root="/api")) == ["prwatch /api"]
        board.full.clear()
        assert _tick(vigils, _vigil(), _vigil(root="/api")) == ["prwatch /app"]

    @staticmethod
    def test_no_more_than_the_limit_run_at_once_and_the_longest_overdue_goes_first():
        board = _Board()
        records = (
            _record(_hello("c1", ago=100, ritual="late")),
            _record(_hello("c2", ago=300, ritual="later")),
        )
        watched = (
            _vigil("late", ritual="late"),
            _vigil("later", ritual="later"),
            _vigil("never", ritual="never"),
        )

        started = _tick(_vigils(board, _Limits(vigils=2)), *watched, records=records)

        assert started == ["never /app", "later /app"]
        assert board.asked == [("/app", "/app/.git"), ("/app", "/app/.git")]

    @staticmethod
    def test_a_vigil_s_cast_still_open_counts_toward_the_limit():
        board = _Board()
        board.seen(_hello("c1", ritual="sweep", vigil="nightly"), "running")
        left = _record(
            _hello("c2", ritual="tidy", vigil="tidy", pid=_LIVE_PID), "running"
        )

        started = _tick(_vigils(board, _Limits(vigils=2)), _vigil(), records=(left,))

        assert started == []
        assert not board.asked

    @staticmethod
    def test_a_cast_no_vigil_started_and_one_that_ended_do_not():
        board = _Board()
        board.seen(_hello("c1", ritual="sweep"), "running")
        board.seen(_hello("c2", ritual="tidy", vigil="tidy"), "ok")

        assert _tick(_vigils(board, _Limits(vigils=1)), _vigil()) == ["prwatch /app"]
