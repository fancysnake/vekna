import asyncio
import io
from datetime import UTC, datetime

import pytest

from tests.conftest import Tty
from vekna.lexicon import StandalonePromptError
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed


def _renderer(
    text: str, *, tty: bool = False
) -> tuple[StandaloneRenderer, io.StringIO]:
    out = Tty() if tty else io.StringIO()
    return StandaloneRenderer(out=out, inp=io.StringIO(text)), out


class TestRender:
    @staticmethod
    def test_writes_rite_name_to_output():
        renderer, out = _renderer("")
        event = RiteBegan(
            rite_id="r1",
            parent_id=None,
            name="run_tests",
            category="step",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        renderer.render(event)

        assert "run_tests" in out.getvalue()

    @staticmethod
    def test_renders_delta_indented_under_its_rite():
        renderer, out = _renderer("")
        started = RiteBegan(
            rite_id="r1",
            parent_id=None,
            name="fix",
            category="medium",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        delta = RiteStreamed(rite_id="r1", delta="one\ntwo")

        renderer.render(started)
        renderer.render(delta)

        assert "  one\n  two\n" in out.getvalue()

    @staticmethod
    def test_a_summary_rides_the_lines_that_open_and_close_the_rite():
        renderer, out = _renderer("")

        renderer.render(_began("r2", parent="r1", summary="mise run lint:py"))
        renderer.render(_ended("r2"))

        assert out.getvalue() == (
            "  ↳ shell  mise run lint:py\n  ✓ shell  mise run lint:py\n"
        )

    @staticmethod
    def test_marks_a_failed_rite_and_names_an_unseen_one_by_id():
        renderer, out = _renderer("")
        ended = RiteEnded(
            rite_id="r9",
            status="error",
            result=None,
            finished_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        renderer.render(ended)

        assert out.getvalue() == "✗ r9\n"


def _began(
    rite_id: str,
    *,
    parent: str | None = None,
    name: str = "shell",
    summary: str | None = None,
) -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id,
        parent_id=parent,
        name=name,
        category="medium" if parent else "step",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        summary=summary,
    )


def _ended(rite_id: str, *, status: str = "ok") -> RiteEnded:
    return RiteEnded(
        rite_id=rite_id,
        status=status,
        result=None,
        finished_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class TestConcurrentRites:
    @staticmethod
    def test_holds_each_sibling_output_until_that_sibling_ends():
        renderer, out = _renderer("")

        for event in (
            _began("r1", name="gates"),
            _began("r2", parent="r1"),
            _began("r3", parent="r1"),
            RiteStreamed(rite_id="r2", delta="lint"),
            RiteStreamed(rite_id="r3", delta="tests"),
            _ended("r3"),
            _ended("r2"),
            _ended("r1"),
        ):
            renderer.render(event)

        assert out.getvalue() == (
            "▶ gates\n"
            "  ↳ shell\n"
            "  ↳ shell\n"
            "    tests\n"
            "  ✓ shell\n"
            "    lint\n"
            "  ✓ shell\n"
            "✓ gates\n"
        )

    @staticmethod
    def test_a_sole_rite_still_streams_live():
        renderer, out = _renderer("")

        for event in (
            _began("r1", name="measure"),
            _began("r2", parent="r1"),
            RiteStreamed(rite_id="r2", delta="running"),
        ):
            renderer.render(event)

        # Before the rite ends, not merely by the time it has: a renderer that
        # buffered until _ended would satisfy the final assertion alone.
        assert out.getvalue() == "▶ measure\n  ↳ shell\n    running\n"

        renderer.render(_ended("r2"))

        assert out.getvalue() == "▶ measure\n  ↳ shell\n    running\n  ✓ shell\n"

    @staticmethod
    def test_a_failed_sibling_still_emits_what_it_had():
        renderer, out = _renderer("")

        for event in (
            _began("r1", name="gates"),
            _began("r2", parent="r1"),
            _began("r3", parent="r1"),
            RiteStreamed(rite_id="r2", delta="boom"),
            _ended("r2", status="error"),
        ):
            renderer.render(event)

        assert out.getvalue().endswith("    boom\n  ✗ shell\n")

    @staticmethod
    def test_a_nested_rite_emits_inside_its_holding_ancestor_block():
        renderer, out = _renderer("")

        for event in (
            _began("r1", name="gates"),
            _began("r2", parent="r1"),
            _began("r3", parent="r1"),
            _began("r4", parent="r2", name="inner"),
            RiteStreamed(rite_id="r4", delta="deep"),
            _ended("r4"),
            _ended("r2"),
        ):
            renderer.render(event)

        assert out.getvalue().endswith(
            "    ↳ inner\n      deep\n    ✓ inner\n  ✓ shell\n"
        )


class TestDecide:
    @staticmethod
    def test_chooses_by_number():
        renderer, _ = _renderer("2\n")

        choice = asyncio.run(renderer.decide(prompt="pick", options=["a", "b"]))

        assert choice == "b"

    @staticmethod
    def test_chooses_by_name():
        renderer, _ = _renderer("a\n")

        choice = asyncio.run(renderer.decide(prompt="pick", options=["a", "b"]))

        assert choice == "a"

    @staticmethod
    def test_raises_after_repeated_invalid_input():
        renderer, _ = _renderer("x\nx\nx\n")

        with pytest.raises(StandalonePromptError):
            asyncio.run(renderer.decide(prompt="pick", options=["a", "b"]))

    # "²" is a digit to `str.isdigit` and not a number to `int`, which used to
    # raise where this prompt has an answer for anything else typed at it.
    @staticmethod
    def test_a_digit_that_is_not_a_number_is_an_invalid_choice():
        renderer, out = _renderer("²\na\n")

        choice = asyncio.run(renderer.decide(prompt="pick", options=["a", "b"]))

        assert (choice, "invalid choice" in out.getvalue()) == ("a", True)


class TestDecideSuggested:
    @staticmethod
    def test_answers_past_the_options():
        renderer, _ = _renderer("neither, do c\n")

        answer = asyncio.run(
            renderer.decide(prompt="pick", options=["a", "b"], free=True)
        )

        assert answer == "neither, do c"

    @staticmethod
    def test_a_number_still_picks_its_option():
        renderer, _ = _renderer("2\n")

        answer = asyncio.run(
            renderer.decide(prompt="pick", options=["a", "b"], free=True)
        )

        assert answer == "b"

    @staticmethod
    def test_says_the_options_are_suggestions():
        renderer, out = _renderer("2\n")

        asyncio.run(renderer.decide(prompt="pick", options=["a", "b"], free=True))

        assert "or answer in your own words" in out.getvalue()

    @staticmethod
    def test_a_digit_that_is_not_a_number_stands_as_the_answer():
        renderer, _ = _renderer("²\n")

        answer = asyncio.run(
            renderer.decide(prompt="pick", options=["a", "b"], free=True)
        )

        assert answer == "²"

    # A suggested prompt cannot be answered wrongly, so a bare return is not a
    # retry — it is an empty answer, and the cast moves on with it.
    @staticmethod
    def test_an_empty_answer_stands():
        renderer, _ = _renderer("\n")

        answer = asyncio.run(
            renderer.decide(prompt="pick", options=["a", "b"], free=True)
        )

        assert not answer


class TestPromptEndOfInput:
    # Closed input is the channel going away, not a wrong answer: every prompt
    # says so the same way rather than one claiming an invalid choice.
    @staticmethod
    def test_a_suggested_prompt_says_the_input_ended():
        renderer, _ = _renderer("")

        with pytest.raises(StandalonePromptError, match="input ended"):
            asyncio.run(renderer.decide(prompt="pick", options=["a", "b"], free=True))

    @staticmethod
    def test_a_free_text_prompt_says_the_input_ended():
        renderer, _ = _renderer("")

        with pytest.raises(StandalonePromptError, match="input ended"):
            asyncio.run(renderer.decide(prompt="name?", free=True))


class TestDecideConfirm:
    @staticmethod
    def test_yes_answer():
        renderer, _ = _renderer("yes\n")

        assert asyncio.run(renderer.decide(prompt="ok?")) == "yes"

    @staticmethod
    def test_no_answer():
        renderer, _ = _renderer("n\n")

        assert asyncio.run(renderer.decide(prompt="ok?")) == "no"

    @staticmethod
    def test_raises_after_repeated_invalid_input():
        renderer, _ = _renderer("maybe\nmaybe\nmaybe\n")

        with pytest.raises(StandalonePromptError):
            asyncio.run(renderer.decide(prompt="ok?"))


class TestDecideFree:
    @staticmethod
    def test_returns_free_text():
        renderer, _ = _renderer("a branch name\n")

        answer = asyncio.run(renderer.decide(prompt="name?", free=True))

        assert answer == "a branch name"


class TestNotify:
    @staticmethod
    def test_a_question_raises_a_desktop_notification():
        renderer, out = _renderer("y\n", tty=True)

        asyncio.run(renderer.decide(prompt="deploy?"))

        assert "\x1b]777;notify;vekna needs you;deploy?\x07" in out.getvalue()

    @staticmethod
    def test_each_event_carries_its_own_title():
        renderer, out = _renderer("", tty=True)

        renderer.notify("done", "countdown")
        renderer.notify("failed", "countdown: out of steps")

        assert out.getvalue() == (
            "\x1b]777;notify;vekna finished;countdown\x07"
            "\x1b]777;notify;vekna failed;countdown: out of steps\x07"
        )

    @staticmethod
    def test_a_stream_that_is_not_a_terminal_gets_no_escape_codes():
        renderer, out = _renderer("y\n")

        asyncio.run(renderer.decide(prompt="deploy?"))

        assert "\x1b" not in out.getvalue()

    @staticmethod
    def test_the_body_cannot_end_the_sequence_early():
        renderer, out = _renderer("y\n", tty=True)

        asyncio.run(renderer.decide(prompt="one\ntwo\x07three\x1b[2J"))

        assert "\x1b]777;notify;vekna needs you;onetwothree[2J\x07" in out.getvalue()

    @staticmethod
    def test_a_long_body_is_truncated():
        renderer, out = _renderer("", tty=True)

        renderer.notify("done", "x" * 500)

        assert out.getvalue() == f"\x1b]777;notify;vekna finished;{'x' * 120}\x07"
