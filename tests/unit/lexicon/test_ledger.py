from datetime import UTC, datetime

from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import Resumption
from vekna.wire import CastHello, CastMessage, RiteFinished, RiteStarted, RunRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _ledger(*events: CastMessage) -> Ledger:
    return Ledger.from_resumption(
        Resumption(
            record=RunRecord(
                hello=CastHello(
                    cast_id="c0",
                    project_root="/proj",
                    ritual="job",
                    components={},
                    started_at=_WHEN,
                )
            ),
            events=list(events),
        )
    )


def _started(rite_id: str, *, name: str, category: str = "medium") -> RiteStarted:
    return RiteStarted(
        cast_id="c0",
        rite_id=rite_id,
        parent_id=None,
        name=name,
        category=category,
        started_at=_WHEN,
    )


def _finished(rite_id: str, *, result: object = None, status: str = "ok"):
    return RiteFinished(
        cast_id="c0", rite_id=rite_id, status=status, result=result, finished_at=_WHEN
    )


class TestWhatReplays:
    @staticmethod
    def test_a_medium_that_finished_hands_back_what_it_recorded():
        ledger = _ledger(
            _started("r1", name="shell"), _finished("r1", result={"exit_code": 0})
        )

        assert ledger.take(rite_id="r1", name="shell") == {"exit_code": 0}

    @staticmethod
    def test_a_step_is_not_replayed_whatever_it_returned():
        ledger = _ledger(
            _started("r1", name="work", category="step"),
            _finished("r1", result={"went": "left"}),
        )

        assert ledger.take(rite_id="r1", name="work") is None

    # Recorded-nothing and recorded-a-null are the same answer from `take`, so a
    # rite held with no result would run again while the ledger stayed unspent.
    @staticmethod
    def test_a_medium_that_recorded_nothing_is_not_replayed():
        ledger = _ledger(_started("r1", name="shell"), _finished("r1"))

        assert ledger.take(rite_id="r1", name="shell") is None

    @staticmethod
    def test_a_rite_that_failed_is_not_replayed():
        ledger = _ledger(
            _started("r1", name="shell"),
            _finished("r1", result={"exit_code": 1}, status="error"),
        )

        assert ledger.take(rite_id="r1", name="shell") is None


class TestSpending:
    # Rite ids line up only while the resumed cast walks the path the recorded
    # one walked, so the first rite that does not match ends the replay.
    @staticmethod
    def test_a_miss_spends_the_whole_ledger():
        ledger = _ledger(
            _started("r1", name="shell"),
            _finished("r1", result={"exit_code": 0}),
            _started("r2", name="coding"),
            _finished("r2", result={"text": "done"}),
        )

        assert ledger.take(rite_id="r1", name="coding") is None
        assert ledger.take(rite_id="r2", name="coding") is None
