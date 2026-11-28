from datetime import UTC, datetime, timedelta

import pytest

from vekna.gates.cli.cast_text import began, printable
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


@pytest.mark.usefixtures("_tokyo")
class TestBegan:
    # `_WHEN` is 09:00 on Jan 01 in Tokyo, 15 hours before the day turns there.
    @staticmethod
    @pytest.mark.parametrize(
        ("since", "said"),
        [
            (timedelta(seconds=30), "09:00"),
            (timedelta(hours=14, minutes=59), "09:00"),
            (timedelta(hours=15), "Jan 01 09:00"),
            (timedelta(days=40), "Jan 01 09:00"),
        ],
    )
    def test_an_ended_cast_says_when_it_began_by_the_readers_clock(
        since: timedelta, said: str
    ):
        assert began(_view("ok"), _WHEN + since) == said

    @staticmethod
    def test_a_live_cast_is_now_however_long_it_has_run():
        assert began(_view("running"), _WHEN + timedelta(days=3)) == "@now"


class TestPrintable:
    @staticmethod
    def test_an_escape_sequence_goes_and_a_stray_control_character_is_shown():
        said = "\x1b[31mred\x1b[0m \x1b]8;;http://x\x1b\\link\x07 bell\x07 csi\x9b2K"

        assert printable(said) == "red link� bell� csi�2K"

    @staticmethod
    def test_an_unterminated_sequence_does_not_swallow_the_next_line():
        assert printable("one \x1b]0;title\ntwo") == "one \ntwo"
