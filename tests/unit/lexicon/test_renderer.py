import asyncio
import io
from datetime import UTC, datetime

import pytest

from vekna.lexicon import StandalonePromptError
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed


def _renderer(text: str) -> tuple[StandaloneRenderer, io.StringIO]:
    out = io.StringIO()
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
    rite_id: str, *, parent: str | None = None, name: str = "shell"
) -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id,
        parent_id=parent,
        name=name,
        category="medium" if parent else "step",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
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
