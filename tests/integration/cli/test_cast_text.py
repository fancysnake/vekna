from datetime import UTC, datetime, timedelta

import pytest

from vekna.gates.cli.cast_text import ago, printable
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
            (timedelta(minutes=5), "@<1h"),
            (timedelta(hours=1), "@<3h"),
            (timedelta(hours=3, minutes=59), "@<6h"),
            (timedelta(hours=11), "@<12h"),
            (timedelta(hours=23), "@<1d"),
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


class TestPrintable:
    @staticmethod
    def test_an_escape_sequence_goes_and_a_stray_control_character_is_shown():
        said = "\x1b[31mred\x1b[0m \x1b]8;;http://x\x1b\\link\x07 bell\x07 csi\x9b2K"

        assert printable(said) == "red link� bell� csi�2K"

    @staticmethod
    def test_an_unterminated_sequence_does_not_swallow_the_next_line():
        assert printable("one \x1b]0;title\ntwo") == "one \ntwo"
