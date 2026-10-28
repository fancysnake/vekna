from datetime import UTC, datetime, timedelta

import pytest

from vekna.gates.cli.cast_text import ago
from vekna.pacts.casts import CastView
from vekna.wire import CastHello, CastStatus

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


def _view(status: CastStatus) -> CastView:
    hello = CastHello(
        cast_id="c1",
        project_root="/proj",
        ritual="nap",
        components={},
        started_at=_WHEN,
    )
    return CastView(hello=hello, status=status)


class TestAgo:
    @staticmethod
    @pytest.mark.parametrize(
        ("since", "said"),
        [
            (timedelta(seconds=30), "@now"),
            (timedelta(minutes=5), "@5m ago"),
            (timedelta(hours=3, minutes=59), "@3h ago"),
            (timedelta(days=2, hours=1), "@2d ago"),
        ],
    )
    def test_an_ended_cast_is_placed_by_how_long_ago_it_began(
        since: timedelta, said: str
    ):
        assert ago(_view("ok"), _WHEN + since) == said

    @staticmethod
    def test_a_live_cast_is_now_however_long_it_has_run():
        assert ago(_view("running"), _WHEN + timedelta(days=3)) == "@now"
