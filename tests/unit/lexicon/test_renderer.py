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


class TestApprove:
    @staticmethod
    def test_yes_is_true():
        renderer, _ = _renderer("yes\n")

        assert asyncio.run(renderer.approve(prompt="ok?")) is True

    @staticmethod
    def test_no_is_false():
        renderer, _ = _renderer("n\n")

        assert asyncio.run(renderer.approve(prompt="ok?")) is False


class TestAsk:
    @staticmethod
    def test_returns_free_text():
        renderer, _ = _renderer("a branch name\n")

        assert asyncio.run(renderer.ask(prompt="name?")) == "a branch name"

    @staticmethod
    def test_rejects_value_outside_choices():
        renderer, _ = _renderer("z\nz\nz\n")

        with pytest.raises(StandalonePromptError):
            asyncio.run(renderer.ask(prompt="pick", choices=["x", "y"]))
