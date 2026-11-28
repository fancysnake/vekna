from datetime import UTC, datetime, timedelta

import pytest

from vekna.gates.cli.streaks import streaks
from vekna.pacts.casts import CastView
from vekna.wire import CastHello

_NOW = datetime(2026, 1, 10, tzinfo=UTC)
_SECOND = timedelta(seconds=1)
_MINUTE = timedelta(minutes=1)
_HOUR = timedelta(hours=1)
_DAY = timedelta(days=1)


def _ended(cast_id: str, age: timedelta) -> CastView:
    hello = CastHello(
        cast_id=cast_id,
        project_root="/proj",
        ritual="nap",
        components={},
        started_at=_NOW - age,
    )
    return CastView(hello=hello, status="ok")


class TestStreaks:
    @staticmethod
    @pytest.mark.parametrize(
        ("older", "newer"),
        [
            (_MINUTE - _SECOND, _SECOND),
            (_HOUR - _SECOND, _MINUTE),
            (3 * _HOUR - _SECOND, _HOUR),
            (6 * _HOUR - _SECOND, 3 * _HOUR),
            (12 * _HOUR - _SECOND, 6 * _HOUR),
            (_DAY - _SECOND, 12 * _HOUR),
            (2 * _DAY - _SECOND, _DAY),
        ],
    )
    def test_casts_of_one_slot_are_one_streak(older: timedelta, newer: timedelta):
        views = [_ended("c1", older), _ended("c2", newer)]

        assert len(streaks(views, {}, now=_NOW)) == 1

    @staticmethod
    @pytest.mark.parametrize(
        "boundary", [_MINUTE, _HOUR, 3 * _HOUR, 6 * _HOUR, 12 * _HOUR, _DAY, 2 * _DAY]
    )
    def test_a_slot_boundary_cuts_a_streak(boundary: timedelta):
        older, newer = _ended("c1", boundary), _ended("c2", boundary - _SECOND)

        assert streaks([older, newer], {}, now=_NOW) == [(newer,), (older,)]
