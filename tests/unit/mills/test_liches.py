from collections.abc import Sequence
from datetime import UTC, datetime

from vekna.mills.liches import draw_name, sleeping_here
from vekna.pacts.lich import Phylactery

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _row(name: str, *, root: str = "/proj", days: int = 0) -> Phylactery:
    return Phylactery(
        name=name, root=root, created=_WHEN.replace(day=1 + days), last_cast=None
    )


# A draw that hands back the words in a fixed order, so a test asserts on the
# name rather than on the fact that one came back.
def _drawing(*words: str):
    queued = iter(words)

    def choose(_: Sequence[str]) -> str:
        return next(queued)

    return choose


class TestDrawName:
    @staticmethod
    def test_a_name_is_two_words_from_the_list():
        drawn = draw_name(taken=(), choose=_drawing("hollow", "vesper"))

        assert drawn == "hollow-vesper"

    # Against every row, live or dormant: the name is the key, and a dormant
    # lich answering to it is how a revive reaches the wrong station.
    @staticmethod
    def test_a_name_somebody_holds_is_drawn_again():
        drawn = draw_name(
            taken={"hollow-vesper"},
            choose=_drawing("hollow", "vesper", "ashen", "quill"),
        )

        assert drawn == "ashen-quill"

    # The unlucky end of the same rule: the draw keeps coming back taken, so the
    # name gets a number instead of the loop running forever.
    @staticmethod
    def test_a_draw_that_never_comes_up_free_ends_in_a_number():
        drawn = draw_name(
            taken={"hollow-vesper"}, choose=_drawing(*["hollow", "vesper"] * 21)
        )

        assert drawn == "hollow-vesper-2"


class TestSleepingHere:
    @staticmethod
    def test_only_the_rows_rooted_in_this_directory_are_offered():
        rows = [_row("hollow-vesper"), _row("ashen-quill", root="/elsewhere")]

        offered = sleeping_here(rows, root="/proj")

        assert [row.name for row in offered] == ["hollow-vesper"]

    @staticmethod
    def test_the_most_recently_raised_comes_first():
        rows = [_row("hollow-vesper"), _row("ashen-quill", days=2)]

        offered = sleeping_here(rows, root="/proj")

        assert [row.name for row in offered] == ["ashen-quill", "hollow-vesper"]

    @staticmethod
    def test_a_directory_with_nothing_in_it_offers_nothing():
        assert sleeping_here([_row("hollow-vesper")], root="/somewhere-else") == []
