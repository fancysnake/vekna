import asyncio
import io
from datetime import datetime, timezone

import pytest

from vekna.lexicon import StandalonePromptError, StandaloneRenderer
from vekna.wire import RiteStarted


def _renderer(text: str) -> tuple[StandaloneRenderer, io.StringIO]:
    out = io.StringIO()
    return StandaloneRenderer(out=out, inp=io.StringIO(text)), out


class TestEmit:
    @staticmethod
    def test_writes_rite_name_to_output():
        renderer, out = _renderer("")
        event = RiteStarted(
            cast_id="c1",
            rite_id="r1",
            parent_id=None,
            name="run_tests",
            category="step",
            started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        asyncio.run(renderer.emit(event))

        assert "run_tests" in out.getvalue()


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
