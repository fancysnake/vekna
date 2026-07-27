import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from vekna.folio.coding import (
    CodingOpts,
    CodingOutputError,
    CodingResult,
    CodingSessionError,
    Session,
    coding,
    register,
)
from vekna.lexicon import (
    FocusMissingError,
    FocusReply,
    NoComponents,
    Transition,
    done,
    goto,
    register_focus,
    ritual,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, reset_registry, run_cast
from vekna.lexicon._pacts import RiteEnded, RiteStreamed


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


class FakeFocus:
    def __init__(
        self,
        *,
        text: str = "all done",
        deltas: tuple[str, ...] = (),
        gate_tools: tuple[str, ...] = (),
        questions: tuple[tuple[str, tuple[str, ...] | None], ...] = (),
    ) -> None:
        self._reply = FocusReply(text=text, session_id="s1", num_turns=2, cost_usd=0.5)
        self._deltas = deltas
        self._gate_tools = gate_tools
        self._questions = questions
        self.calls = []
        self.gate_answers = []
        self.answers = []

    # What a real focus does: a call that resumes stays on its session, and one
    # that does not is handed a new id. `s1`, `s2`, `s3` by arrival.
    def _session_id(self, call) -> str:
        return call.resume if call.resume is not None else f"s{len(self.calls)}"

    async def run(self, call, *, on_delta, gate, ask):
        self.calls.append(call)
        for delta in self._deltas:
            on_delta(delta)
        if gate is not None:
            for tool in self._gate_tools:
                self.gate_answers.append(await gate(tool))
        for question, options in self._questions:
            self.answers.append(await ask(question, options))
        return self._reply.model_copy(update={"session_id": self._session_id(call)})


class Answer(BaseModel):
    port: int


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry()
    yield
    reset_registry()


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
        async def r(_: NoComponents) -> Transition:
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
        deltas = [e.delta for e in grimoire.events if isinstance(e, RiteStreamed)]
        assert deltas == ["thinking", "editing"]

    @staticmethod
    def test_telemetry_lands_in_medium_rite_result():
        register_focus("coding", FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it")
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _, grimoire = _cast(r)

        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        medium_finish = finished[0]
        assert medium_finish.result == {
            "session": "new",
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
        }

    @staticmethod
    def test_typed_output_validates_the_reply_text():
        focus = FakeFocus(text='{"port": 9000}')
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        result, _ = _cast(r)

        assert result == Answer(port=9000)
        assert focus.calls[0].output_schema is not None

    @staticmethod
    def test_invalid_typed_output_raises():
        register_focus("coding", FakeFocus(text="not json"))

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
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
            await coding("fix it", opts=CodingOpts(gate_tools=["bash"]))
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _cast(r, stdin="n\n")

        assert focus.gate_answers == [False, True]

    @staticmethod
    def test_agent_question_with_options_routes_through_decide():
        focus = FakeFocus(
            questions=(("unit or integration?", ("unit", "integration")),)
        )
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("write the test")
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _cast(r, stdin="2\n")

        assert focus.answers == ["integration"]

    @staticmethod
    def test_agent_question_without_options_asks_for_free_text():
        focus = FakeFocus(questions=(("which fixture?", None),))
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("write the test")
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _cast(r, stdin="the tmp_path one\n")

        assert focus.answers == ["the tmp_path one"]

    @staticmethod
    def test_a_focus_cannot_smuggle_an_unknown_telemetry_key():
        # The old dict-shaped telemetry was splatted into a model with
        # extra="ignore", so a focus spelling cost_usd differently lost the
        # field with no error anywhere.
        with pytest.raises(ValidationError):
            FocusReply(text="done", total_cost_usd=0.5)

    @staticmethod
    def test_missing_focus_raises_with_install_hint():
        # The hint is the folio's own declaration, so the test makes it the way
        # production does — the loader is an integration concern.
        register()

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it")
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        with pytest.raises(FocusMissingError, match="claude-agent-sdk"):
            _cast(r)


class TestSessionDeclaration:
    @staticmethod
    def _resumes(*declarations) -> list[str | None]:
        # One step, one coding call per declaration, so what a call resumes is
        # read off the focus rather than inferred from the reply.
        focus = FakeFocus()
        register_focus("coding", focus)

        @step
        async def work(_: Answer) -> Transition:
            for index, session in enumerate(declarations):
                await coding(f"call {index}", opts=CodingOpts(session=session))
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _cast(r)
        return [call.resume for call in focus.calls]

    @classmethod
    def test_the_default_starts_a_fresh_session_every_time(cls):
        assert cls._resumes(Session.NEW, Session.NEW) == [None, None]

    @classmethod
    @pytest.mark.parametrize("spelling", [Session.CONTINUE, "continue"])
    def test_continue_picks_up_the_session_before_it(cls, spelling):
        assert cls._resumes(Session.NEW, spelling) == [None, "s1"]

    @classmethod
    def test_two_named_threads_do_not_read_each_other(cls):
        assert cls._resumes("repair", "review", "repair") == [None, None, "s1"]

    @classmethod
    def test_continue_follows_the_last_call_whatever_thread_it_was_on(cls):
        # The documented consequence of "the cast's running session": a named
        # rite moves it too, so `continue` after one resumes that name's id.
        assert cls._resumes("repair", Session.CONTINUE) == [None, "s1"]

    @staticmethod
    def test_a_blank_thread_name_is_refused():
        register_focus("coding", FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", opts=CodingOpts(session="  "))
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        with pytest.raises(CodingSessionError, match="not a blank one"):
            _cast(r)

    @staticmethod
    def test_telemetry_names_the_thread_the_author_declared():
        register_focus("coding", FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", opts=CodingOpts(session="repair"))
            return done(None)

        @ritual("r")
        async def r(_: NoComponents) -> Transition:
            await asyncio.sleep(0)
            return goto(work, Answer(port=1))

        _, grimoire = _cast(r)

        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        assert finished[0].result == {
            "session": "repair",
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
        }
