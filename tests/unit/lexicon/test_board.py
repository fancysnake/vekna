import io
from datetime import UTC, datetime, timedelta

import pytest

from vekna.lexicon._links.board import Diverted
from vekna.lexicon._links.picture import Entry, Log, Picture, frame, summary
from vekna.lexicon._links.standalone import StandaloneRenderer, Tail
from vekna.lexicon._links.turns import Turns
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_NOW = _WHEN + timedelta(seconds=65)
_SIZE = (80, 24)
_SHORT_QUESTION = 4
_TALL_QUESTION = 9


def _began(rite_id: str = "r1", name: str = "watch") -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id, parent_id=None, name=name, category="step", started_at=_WHEN
    )


def _ended(rite_id: str = "r1") -> RiteEnded:
    return RiteEnded(rite_id=rite_id, status="ok", result=None, finished_at=_WHEN)


def _queued(label: str, *lines: str) -> Entry:
    log = Log()
    for line in lines:
        log.write(f"{line}\n")
    return Entry(
        label=label, started_at=_WHEN, log=log, renderer=StandaloneRenderer(out=log)
    )


class TestLog:
    @staticmethod
    def test_a_rite_that_said_nothing_inside_itself_is_one_line():
        log = Log()
        renderer = StandaloneRenderer(out=log)

        renderer.render(_began())
        renderer.render(_ended())

        assert log.lines == ["✓ watch"]

    @staticmethod
    def test_a_rite_that_said_something_keeps_every_line():
        log = Log()
        renderer = StandaloneRenderer(out=log)

        renderer.render(_began())
        renderer.render(RiteStreamed(rite_id="r1", delta="checks red"))
        renderer.render(_ended())

        assert log.lines == ["▶ watch", "  checks red", "✓ watch"]

    @staticmethod
    def test_a_mark_the_terminal_gave_takes_nothing_back():
        log = Log()
        log.write("first\n")

        assert not log.overwrite(1, "second\n")
        assert log.lines == ["first"]

    @staticmethod
    def test_text_left_of_a_write_keeps_it_from_going_back():
        log = Log()
        log.write("push? ")
        log.write("yes\n")

        assert not log.overwrite(log.mark, "gone\n")
        assert log.lines == ["push? yes"]


class TestDiverted:
    @staticmethod
    def test_until_it_is_diverted_it_is_the_terminal():
        terminal = io.StringIO()
        diverted = Diverted(Tail(terminal))

        diverted.write("▶ watch\n")
        taken = diverted.overwrite(diverted.mark, "✓ watch\n")
        diverted.flush()

        assert not taken
        assert not diverted.isatty()
        assert terminal.getvalue() == "▶ watch\n"

    @staticmethod
    def test_diverted_its_lines_go_to_its_log_and_a_line_goes_back_there():
        terminal = io.StringIO()
        diverted = Diverted(Tail(terminal))
        diverted.divert()

        diverted.write("")
        diverted.write("▶ watch\n")
        taken = diverted.overwrite(diverted.mark, "✓ watch\n")

        assert taken
        assert diverted.log.isatty()
        assert diverted.log.lines == ["✓ watch"]
        assert not terminal.getvalue()


class TestFrame:
    @staticmethod
    def test_a_line_per_cast_then_the_latest_output_of_the_one_in_view():
        running = _queued("heal aaaa", "▶ repair", "  fixing")
        running.steps["r1"] = "repair"
        done = _queued("heal bbbb")
        done.ended = "ok"
        picture = Picture(
            entries={"a": running, "b": done}, typed="root", view="a", note="hello"
        )

        assert frame(picture, now=_NOW, size=_SIZE).splitlines() == [
            "\x1b[H\x1b[2J  1  heal aaaa  ▶ 1m05s  repair",
            "  2  heal bbbb  ✓ done",
            "── heal aaaa ──",
            "▶ repair",
            "  fixing",
            " hello",
            " a number to view a cast · l its whole log · Ctrl-C leaves them running",
        ]

    @staticmethod
    def test_the_view_is_cut_to_the_rows_left_and_a_line_to_the_width():
        entry = _queued("heal aaaa", *(f"line {n}" for n in range(30)), "x" * 20)
        picture = Picture(entries={"a": entry}, typed="root", view="a")

        lines = frame(picture, now=_NOW, size=(10, 8)).splitlines()

        assert lines[1:5] == ["── heal a…", "line 28", "line 29", "xxxxxxxxx…"]

    @staticmethod
    def test_while_a_question_is_asked_the_foot_is_left_to_it():
        picture = Picture(
            entries={"a": _queued("heal aaaa", "asking")}, typed="root", view="a"
        )

        lines = frame(picture, now=_NOW, size=_SIZE, question_rows=3).splitlines()

        assert lines[1:] == ["── heal aaaa ──", "asking"]

    @staticmethod
    def test_a_taller_question_leaves_fewer_rows_to_the_view():
        entry = _queued("heal aaaa", *(f"line {n}" for n in range(30)))
        picture = Picture(entries={"a": entry}, typed="root", view="a")

        short = frame(picture, now=_NOW, size=(80, 20), question_rows=_SHORT_QUESTION)
        tall = frame(picture, now=_NOW, size=(80, 20), question_rows=_TALL_QUESTION)

        assert short.splitlines()[-1] == "line 29"
        assert (
            len(short.splitlines()) - len(tall.splitlines())
            == _TALL_QUESTION - _SHORT_QUESTION
        )

    @staticmethod
    def test_a_cast_s_clock_counts_seconds_then_minutes_then_hours():
        picture = Picture(entries={"a": _queued("heal aaaa")}, typed="root", view="a")

        clocks = [
            frame(picture, now=_WHEN + timedelta(seconds=took), size=_SIZE)
            .splitlines()[0]
            .rpartition("▶ ")[2]
            for took in (5, 65, 3725)
        ]

        assert clocks == ["5s", "1m05s", "1h02m"]

    @staticmethod
    def test_the_typed_cast_leaves_when_it_ends_well_and_stays_when_it_fails():
        typed = _queued("sweep root")
        picture = Picture(
            entries={"root": typed, "a": _queued("heal aaaa")}, typed="root", view="a"
        )
        typed.ended = "ok"
        left = picture.shown

        typed.ended = "error"

        assert left == ["a"]
        assert picture.shown == ["root", "a"]


class TestNextRunning:
    @staticmethod
    def test_it_is_the_next_to_have_arrived_that_still_runs_around_the_end():
        entries = {name: _queued(name) for name in ("a", "b", "c")}
        entries["c"].ended = "ok"
        picture = Picture(entries=entries, typed="root", view="a")

        assert picture.next_running("a") == "b"
        assert picture.next_running("b") == "a"

    @staticmethod
    def test_with_nothing_else_running_there_is_none():
        entries = {name: _queued(name) for name in ("a", "b")}
        entries["b"].ended = "error"

        picture = Picture(entries=entries, typed="root", view="a")

        assert picture.next_running("a") is None


class TestSummary:
    @staticmethod
    def test_it_leaves_the_typed_cast_s_lines_a_line_per_cast_and_failed_logs():
        typed = _queued("sweep root")
        typed.ended = "ok"
        typed.log.write("result: null\n")
        done = _queued("heal aaaa", "✓ repair")
        done.ended = "ok"
        failed = _queued("heal bbbb", "▶ repair", "  no remote")
        failed.ended, failed.notice = "error", "push refused"
        going = _queued("heal cccc", "▶ repair")
        picture = Picture(
            entries={"root": typed, "a": done, "b": failed, "c": going},
            typed="root",
            view="a",
        )

        assert summary(picture, now=_NOW).splitlines() == [
            "result: null",
            "  1  heal aaaa  ✓ done",
            "  2  heal bbbb  ✗ failed: push refused",
            "  3  heal cccc  ▶ 1m05s",
            "── heal bbbb ──",
            "▶ repair",
            "  no remote",
        ]


class TestTurns:
    @staticmethod
    def test_a_cast_s_lines_are_held_until_the_one_before_it_ends():
        out = io.StringIO()
        turns = Turns(out)
        turns.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        turns.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        turns.render("b", _began())
        turns.render("b", _ended())
        turns.ended(cast_id="b", status="ok", detail=None)
        turns.render("a", _began())
        held = out.getvalue()

        turns.render("a", _ended())
        turns.ended(cast_id="a", status="error", detail="boom")

        assert held == "[heal aaaa] ▶ watch\n"
        assert out.getvalue().splitlines() == [
            "[heal aaaa] ▶ watch",
            "[heal aaaa] ✓ watch",
            "[heal aaaa] ✗ failed: boom",
            "[heal bbbb] ▶ watch",
            "[heal bbbb] ✓ watch",
            "[heal bbbb] ✓ done",
        ]

    @staticmethod
    def test_a_rite_under_one_of_two_running_at_once_keeps_both_its_lines():
        out = io.StringIO()
        turns = Turns(out)
        turns.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        turns.render("a", _began("s"))
        for rite_id, parent_id in (("m1", "s"), ("m2", "s"), ("inner", "m1")):
            turns.render(
                "a",
                RiteBegan(
                    rite_id=rite_id,
                    parent_id=parent_id,
                    name=rite_id,
                    category="medium",
                    started_at=_WHEN,
                ),
            )

        turns.render("a", _ended("inner"))
        turns.render("a", _ended("m1"))

        assert out.getvalue().splitlines() == [
            "[heal aaaa] ▶ watch",
            "[heal aaaa]   ↳ m1",
            "[heal aaaa]   ↳ m2",
            "[heal aaaa]     ↳ inner",
            "[heal aaaa]     ✓ inner",
            "[heal aaaa]   ✓ m1",
        ]

    @staticmethod
    def test_a_cast_arriving_after_the_others_ended_speaks_at_once():
        out = io.StringIO()
        turns = Turns(out)
        turns.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        turns.ended(cast_id="a", status="ok", detail=None)

        turns.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        turns.render("b", _began())

        assert out.getvalue().splitlines() == [
            "[heal aaaa] ✓ done",
            "[heal bbbb] ▶ watch",
        ]

    @staticmethod
    def test_a_notice_is_said_at_once_whoever_is_speaking():
        out = io.StringIO()
        turns = Turns(out)
        turns.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        turns.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)

        turns.say(cast_id="b", label="heal bbbb", line="⏸ push? — answer it in `vekna`")
        turns.say(
            cast_id="stranger0",
            label="stranger",
            line="⏸ merge? — answer it in `vekna`",
        )

        assert out.getvalue() == (
            "[heal bbbb] ⏸ push? — answer it in `vekna`\n"
            "[stranger] ⏸ merge? — answer it in `vekna`\n"
        )

    @staticmethod
    @pytest.mark.asyncio
    async def test_closing_says_what_was_still_held():
        out = io.StringIO()
        turns = Turns(out)
        turns.entered(cast_id="a", label="heal aaaa", started_at=_WHEN)
        turns.entered(cast_id="b", label="heal bbbb", started_at=_WHEN)
        turns.render("b", _began())

        await turns.close()

        assert out.getvalue() == "[heal bbbb] ▶ watch\n"
