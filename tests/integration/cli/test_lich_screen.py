from datetime import UTC, datetime, timedelta

from vekna.gates.cli.lich import listing, raising_prompt, refusal, session
from vekna.pacts.lich import LichLine, Phylactery
from vekna.wire import CastHello, CastRefused, LichStatus, RunRecord

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _row(name: str = "hollow-vesper", *, last: str | None = None) -> Phylactery:
    return Phylactery(
        name=name, root="/proj", created=_WHEN - timedelta(days=3), last_cast=last
    )


def _record(ritual: str = "fix_demo", *, ago: timedelta) -> RunRecord:
    return RunRecord(
        hello=CastHello(
            cast_id="c1abcdef99",
            project_root="/proj",
            ritual=ritual,
            components={},
            started_at=_WHEN - ago,
        )
    )


def _line(
    *,
    row: Phylactery | None = None,
    live: bool = False,
    said: LichStatus | None = None,
    last: RunRecord | None = None,
) -> LichLine:
    return LichLine(row=_row() if row is None else row, live=live, said=said, last=last)


class TestListing:
    @staticmethod
    def test_a_dormant_lich_says_so_and_says_where_it_stands():
        printed = listing([_line()], now=_WHEN)

        assert "hollow-vesper" in printed
        assert "dormant" in printed
        assert "/proj" in printed

    @staticmethod
    def test_a_live_lich_is_idle_or_casting():
        idle = _line(live=True, said=LichStatus(lich="hollow-vesper"))
        busy = _line(
            live=True,
            said=LichStatus(lich="hollow-vesper", ritual="fix_demo", since=_WHEN),
        )

        assert "idle" in listing([idle], now=_WHEN)
        assert "casting fix_demo" in listing([busy], now=_WHEN)

    # What each last did is the only thing telling two rows in one directory
    # apart, and it is read out of the journal rather than kept twice.
    @staticmethod
    def test_the_last_cast_is_named_and_dated():
        line = _line(row=_row(last="c1abcdef99"), last=_record(ago=timedelta(days=3)))

        assert "last cast fix_demo, 3d ago" in listing([line], now=_WHEN)

    @staticmethod
    def test_a_lich_that_has_cast_nothing_says_that_instead():
        assert "cast nothing yet" in listing([_line()], now=_WHEN)

    # A row whose cast the daemon never journalled: the id is all there is, and
    # saying it is better than inventing a ritual name.
    @staticmethod
    def test_a_cast_the_journal_never_saw_shows_as_its_id():
        line = _line(row=_row(last="c1abcdef99"), last=None)

        assert "last cast c1abcdef" in listing([line], now=_WHEN)

    @staticmethod
    def test_no_liches_says_how_to_raise_one():
        assert "`vekna lich` raises one here" in listing([])


class TestRaisingPrompt:
    @staticmethod
    def test_one_sleeper_is_offered_by_number_or_a_new_one():
        printed = raising_prompt([_line()], now=_WHEN)

        assert "One lich sleeps here." in printed
        assert "[1] hollow-vesper" in printed
        assert "[n] a new one" in printed

    @staticmethod
    def test_two_sleepers_are_counted():
        printed = raising_prompt([_line(), _line(row=_row("ashen-quill"))], now=_WHEN)

        assert "2 liches sleep here." in printed


class TestSession:
    @staticmethod
    def test_an_idle_lich_says_so_and_shows_the_vocabulary():
        painted = session(said=LichStatus(lich="hollow-vesper"), now=_WHEN)

        assert painted.startswith("hollow-vesper · idle")
        assert "cast <ritual>" in painted
        assert "kill" in painted

    # Four minutes is working, forty is stuck, and that is the whole reason the
    # line carries a clock.
    @staticmethod
    def test_a_casting_lich_says_what_and_for_how_long():
        said = LichStatus(
            lich="hollow-vesper",
            ritual="merge_ready",
            since=_WHEN - timedelta(minutes=4),
        )

        painted = session(said=said, now=_WHEN)

        assert "casting merge_ready for 4m" in painted

    @staticmethod
    def test_the_ritual_s_own_line_sits_under_the_lich_s():
        said = LichStatus(lich="hollow-vesper", ritual="merge_ready", since=_WHEN)

        painted = session(said=said, ritual_line="PR #412 · lint", now=_WHEN).split(
            "\n"
        )

        assert painted[0].startswith("hollow-vesper · casting merge_ready")
        assert painted[1] == "  PR #412 · lint"

    @staticmethod
    def test_a_lich_that_has_said_nothing_yet_shows_as_waiting():
        assert session(said=None, now=_WHEN).startswith("…")


class TestRefusal:
    @staticmethod
    def test_it_names_what_runs_how_long_and_the_way_out():
        message = CastRefused(
            lich="hollow-vesper",
            ritual="merge_ready",
            since=_WHEN - timedelta(minutes=90),
        )

        said = refusal(message, now=_WHEN)

        assert "hollow-vesper is casting merge_ready" in said
        assert "1h30m in" in said
        assert "`kill` is the way out" in said
