import asyncio
import io
from datetime import datetime, timezone

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
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
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
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
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
            finished_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        renderer.render(ended)

        assert out.getvalue() == "✗ r9\n"


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
