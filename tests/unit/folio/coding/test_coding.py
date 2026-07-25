import asyncio
import io
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel, JsonValue

from vekna.folio.coding import CodingOpts, CodingOutputError, CodingResult, coding
from vekna.lexicon import (
    FocusMissingError,
    FocusReply,
    Grimoire,
    StandaloneRenderer,
    Transition,
    done,
    goto,
    register_focus,
    ritual,
    run_cast,
    step,
)
from vekna.wire import RiteDelta, RiteFinished


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeFocus:
    def __init__(
        self,
        *,
        text: str = "all done",
        structured: JsonValue | None = None,
        deltas: tuple[str, ...] = (),
        gate_tools: tuple[str, ...] = (),
    ) -> None:
        self._text = text
        self._structured = structured
        self._deltas = deltas
        self._gate_tools = gate_tools
        self.calls = []
        self.gate_answers = []

    async def run(self, call, *, on_delta, gate):
        self.calls.append(call)
        for delta in self._deltas:
            on_delta(delta)
        if gate is not None:
            for tool in self._gate_tools:
                self.gate_answers.append(await gate(tool))
        return FocusReply(
            text=self._text,
            structured=self._structured,
            telemetry={"session_id": "s1", "num_turns": 2, "cost_usd": 0.5},
        )


class Answer(BaseModel):
    port: int


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr("vekna.lexicon._mills._foci", {})


def _cast(the_ritual, *, stdin: str = "") -> tuple[object, Grimoire]:
    renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO(stdin))
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=renderer,
        )
    )
    return result, grimoire


class TestCodingMedium:
    @staticmethod
    def test_default_return_is_telemetry_result():
        focus = FakeFocus(deltas=("thinking", "editing"))
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            opts = CodingOpts(model="opus", cwd="/tmp/x")
            return done(await coding("fix it", opts=opts))

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        result, grimoire = _cast(r)

        assert result == CodingResult(
            text="all done", session_id="s1", num_turns=2, cost_usd=0.5
        )
        assert len(focus.calls) == 1
        call = focus.calls[0]
        assert call.prompt == "fix it"
        assert call.model == "opus"
        assert call.system is None
        assert call.cwd == "/tmp/x"
        assert call.output_schema is None
        assert call.focus_options is None
        deltas = [e.delta for e in grimoire.events if isinstance(e, RiteDelta)]
        assert deltas == ["thinking", "editing"]

    @staticmethod
    def test_telemetry_lands_in_medium_rite_result():
        register_focus("coding", FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it")
            return done(None)

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _, grimoire = _cast(r)

        finished = [e for e in grimoire.events if isinstance(e, RiteFinished)]
        medium_finish = finished[0]
        assert medium_finish.result == {
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
        }

    @staticmethod
    def test_typed_output_validates_structured_reply():
        focus = FakeFocus(structured={"port": 8080})
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        result, _ = _cast(r)

        assert result == Answer(port=8080)
        assert focus.calls[0].output_schema is not None

    @staticmethod
    def test_typed_output_falls_back_to_text_json():
        register_focus("coding", FakeFocus(text='{"port": 9000}'))

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        result, _ = _cast(r)

        assert result == Answer(port=9000)

    @staticmethod
    def test_invalid_typed_output_raises():
        register_focus("coding", FakeFocus(text="not json"))

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        with pytest.raises(CodingOutputError):
            _cast(r)

    @staticmethod
    def test_gate_tools_route_through_decide():
        focus = FakeFocus(gate_tools=("bash", "read"))
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", gate_tools=["bash"])
            return done(None)

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _cast(r, stdin="n\n")

        assert focus.gate_answers == [False, True]

    @staticmethod
    def test_missing_focus_raises_with_install_hint():
        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it")
            return done(None)

        @ritual("r")
        async def r() -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        with pytest.raises(FocusMissingError, match="claude-agent-sdk"):
            _cast(r)
