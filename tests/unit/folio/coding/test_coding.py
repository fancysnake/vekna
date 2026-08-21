import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from tests.conftest import entry, journalled
from vekna.folio.coding import (
    CodingOpts,
    CodingOptsError,
    CodingOutputError,
    CodingResult,
    CodingSessionError,
    Session,
    coding,
    register,
)
from vekna.lexicon import (
    CODING_FOCUS,
    FocusMissingError,
    FocusReply,
    MediumBoundaryError,
    Transition,
    done,
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
        session_id: str | None = "s1",
    ) -> None:
        self._reply = FocusReply(
            text=text, session_id=session_id, num_turns=2, cost_usd=0.5
        )
        self._deltas = deltas
        self._gate_tools = gate_tools
        self._questions = questions
        self.calls = []
        self.gate_answers = []
        self.answers = []

    # What a real focus does: a call that resumes stays on its session, and one
    # that does not is handed a new id. `s1`, `s2`, `s3` by arrival.
    def _session_id(self, call) -> str | None:
        if self._reply.session_id is None:
            return None
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


def _cast(the_ritual, *, stdin: str = "", ledger=None) -> tuple[object, Grimoire]:
    renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO(stdin))
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=renderer,
            ledger=ledger,
        )
    )
    return result, grimoire


class TestCodingMedium:
    @staticmethod
    def test_default_return_is_telemetry_result():
        focus = FakeFocus(deltas=("thinking", "editing"))
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            opts = CodingOpts(model="opus", cwd="/tmp/x")
            return done(await coding("fix it", opts=opts))

        r = entry(target=work, payload=Answer(port=1))

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
        CODING_FOCUS.register(FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it")
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _, grimoire = _cast(r)

        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        medium_finish = finished[0]
        assert medium_finish.result == {
            "session": "new",
            "key": None,
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
            "text": "all done",
        }

    @staticmethod
    def test_typed_output_validates_the_reply_text():
        focus = FakeFocus(text='{"port": 9000}')
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        r = entry(target=work, payload=Answer(port=1))

        result, _ = _cast(r)

        assert result == Answer(port=9000)
        assert focus.calls[0].output_schema is not None

    @staticmethod
    def test_invalid_typed_output_raises():
        CODING_FOCUS.register(FakeFocus(text="not json"))

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("start server", output=Answer))

        r = entry(target=work, payload=Answer(port=1))

        with pytest.raises(CodingOutputError):
            _cast(r)

    @staticmethod
    def test_gate_tools_route_through_decide():
        focus = FakeFocus(gate_tools=("bash", "read"))
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", opts=CodingOpts(gate_tools=["bash"]))
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _cast(r, stdin="n\n")

        assert focus.gate_answers == [False, True]

    @staticmethod
    def test_focus_options_ride_the_bundle_intact():
        # The bundle carries a Focus's own model, and pydantic hands the Focus
        # back the instance it was given rather than a coerced BaseModel.
        focus = FakeFocus()
        CODING_FOCUS.register(focus)
        knobs = Answer(port=8080)

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", opts=CodingOpts(focus_options=knobs))
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _cast(r)

        assert focus.calls[0].focus_options is knobs

    @staticmethod
    def test_a_bundle_field_of_the_wrong_shape_names_the_field():
        # Every other way of mis-building the bundle reads like the moved knobs:
        # a `RitualError` naming the field, not a pydantic report titled after
        # the validator that caught it.
        with pytest.raises(CodingOptsError, match="model: Input should be") as raised:
            CodingOpts(model=3)

        assert "ValidatorCallable" not in str(raised.value)

    @staticmethod
    def test_agent_question_with_options_routes_through_decide():
        focus = FakeFocus(
            questions=(("unit or integration?", ("unit", "integration")),)
        )
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("write the test")
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _cast(r, stdin="2\n")

        assert focus.answers == ["integration"]

    @staticmethod
    def test_agent_question_without_options_asks_for_free_text():
        focus = FakeFocus(questions=(("which fixture?", None),))
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("write the test")
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

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

        r = entry(target=work, payload=Answer(port=1))

        with pytest.raises(FocusMissingError, match="claude-agent-sdk"):
            _cast(r)


def _one_call_ritual(**declaration):
    @step
    async def work(_: Answer) -> Transition:
        await coding("fix it", **declaration)
        return done(None)

    return entry(target=work, payload=Answer(port=1))


class TestSessionDeclaration:
    @staticmethod
    def _resumes(*declarations) -> list[str | None]:
        # One step, one coding call per `(session, key)` declaration, so what a
        # call resumes is read off the focus rather than inferred from the reply.
        focus = FakeFocus()
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            for index, (session, key) in enumerate(declarations):
                await coding(f"call {index}", session=session, key=key)
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _cast(r)
        return [call.resume for call in focus.calls]

    @classmethod
    def test_the_default_starts_a_fresh_session_every_time(cls):
        assert cls._resumes((Session.NEW, None), (Session.NEW, None)) == [None, None]

    @classmethod
    @pytest.mark.parametrize("spelling", [Session.CONTINUE, "continue"])
    def test_continue_picks_up_the_session_before_it(cls, spelling):
        # The plain string still lands on the member, so an author who never
        # imports `Session` declares the same thing.
        assert cls._resumes((Session.NEW, None), (spelling, None)) == [None, "s1"]

    @classmethod
    def test_two_keyed_threads_do_not_read_each_other(cls):
        assert cls._resumes(
            (Session.CONTINUE, "repair"),
            (Session.CONTINUE, "review"),
            (Session.CONTINUE, "repair"),
        ) == [None, None, "s1"]

    @classmethod
    def test_a_keyed_new_restarts_the_thread_it_files_under(cls):
        # `new` with a key is how a loop starts over: the third call resumes
        # `s2`, what the restart opened, rather than the `s1` before it.
        assert cls._resumes(
            (Session.CONTINUE, "repair"),
            (Session.NEW, "repair"),
            (Session.CONTINUE, "repair"),
        ) == [None, None, "s2"]

    @classmethod
    def test_padding_does_not_open_a_second_thread(cls):
        # Two spellings of one key that would render identically in the
        # journal, so a thread that silently forked would be invisible there.
        assert cls._resumes(
            (Session.CONTINUE, "repair"), (Session.CONTINUE, " repair ")
        ) == [None, "s1"]

    @classmethod
    def test_continue_without_a_key_follows_whatever_ran_last(cls):
        # The documented consequence of "the cast's running session": a keyed
        # rite moves it too, so an unkeyed `continue` after one resumes its id.
        assert cls._resumes((Session.CONTINUE, "repair"), (Session.CONTINUE, None)) == [
            None,
            "s1",
        ]

    @staticmethod
    def test_a_focus_that_reports_no_session_records_nothing():
        # A reply without a session_id leaves the book untouched, so the
        # `continue` after it starts fresh instead of resuming some older call.
        focus = FakeFocus(session_id=None)
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("fix it", session=Session.CONTINUE, key="repair")
            await coding("fix it again", session=Session.CONTINUE)
            return done(None)

        r = entry(target=work, payload=Answer(port=1))

        _, grimoire = _cast(r)

        assert [call.resume for call in focus.calls] == [None, None]
        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        assert finished[0].result == {
            "session": "continue",
            "key": "repair",
            "session_id": None,
            "num_turns": 2,
            "cost_usd": 0.5,
            "text": "all done",
        }

    @staticmethod
    def test_a_declared_thread_that_did_not_take_says_so():
        # The rite that failed to record is the one that reports it: reading
        # `session_id: null` off the journal afterwards is not the same as being
        # told, and the next call on the thread would resume the wrong id.
        CODING_FOCUS.register(FakeFocus(session_id=None))

        _, grimoire = _cast(_one_call_ritual(session=Session.CONTINUE, key="repair"))

        deltas = [e.delta for e in grimoire.events if isinstance(e, RiteStreamed)]
        assert deltas == [
            "the focus reported no session id: nothing recorded for key 'repair'"
        ]

    @staticmethod
    def test_an_unkeyed_continue_that_did_not_take_says_so():
        CODING_FOCUS.register(FakeFocus(session_id=None))

        _, grimoire = _cast(_one_call_ritual(session=Session.CONTINUE))

        deltas = [e.delta for e in grimoire.events if isinstance(e, RiteStreamed)]
        assert deltas == [
            "the focus reported no session id: nothing recorded for the running session"
        ]

    @staticmethod
    def test_a_call_that_declared_no_thread_stays_quiet():
        # Nothing was claimed, so there is nothing to report — a Focus that
        # never reports ids would otherwise narrate every call it answers.
        CODING_FOCUS.register(FakeFocus(session_id=None))

        _, grimoire = _cast(_one_call_ritual())

        assert [e for e in grimoire.events if isinstance(e, RiteStreamed)] == []

    @staticmethod
    @pytest.mark.parametrize("key", ["", "  ", 3, ["repair"]])
    def test_a_key_that_names_nothing_is_refused(key):
        CODING_FOCUS.register(FakeFocus())

        with pytest.raises(CodingSessionError, match="key names the thread"):
            _cast(_one_call_ritual(session=Session.CONTINUE, key=key))

    @staticmethod
    @pytest.mark.parametrize("session", [None, 3, "repair", " new", "New", ""])
    def test_a_word_that_is_not_a_reserved_one_is_refused(session):
        # `"repair"` among them on purpose: a thread name is a `key` now, and
        # the older spelling has to say so rather than open a thread called
        # after whatever it was handed. An author's `rituals.py` is never
        # type-checked, so this is the only place the slip is caught.
        CODING_FOCUS.register(FakeFocus())

        with pytest.raises(CodingSessionError, match="session takes"):
            _cast(_one_call_ritual(session=session))

    @staticmethod
    @pytest.mark.parametrize("knob", ["session", "key"])
    def test_the_thread_is_not_a_knob_on_opts(knob):
        # Per-call identity, not configuration, so a shared `CodingOpts` cannot
        # carry it. `forbid` is what keeps the old spelling from being dropped
        # onto whatever thread the call defaults to, and the refusal is a
        # `RitualError` so the cast reports it rather than unwinding.
        with pytest.raises(CodingOptsError, match=f"no field '{knob}'") as raised:
            CodingOpts(**{knob: "repair"})

        assert "parameters of coding()" in str(raised.value)

    @staticmethod
    def test_the_old_call_spelling_names_the_argument_it_lost():
        # `gate_tools` moved into the bundle, and the call that still passes it
        # is a slip an unchecked rituals.py would carry to runtime — Python's own
        # TypeError would report it as a traceback out of the engine's frames.
        CODING_FOCUS.register(FakeFocus())

        with pytest.raises(MediumBoundaryError, match="takes no argument"):
            _cast(_one_call_ritual(gate_tools=["Bash"]))

    @staticmethod
    def test_telemetry_names_the_thread_the_author_declared():
        CODING_FOCUS.register(FakeFocus())

        _, grimoire = _cast(_one_call_ritual(session=Session.CONTINUE, key="repair"))

        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        assert finished[0].result == {
            "session": "continue",
            "key": "repair",
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
            "text": "all done",
        }

    @staticmethod
    def test_telemetry_carries_a_null_key_when_none_was_declared():
        CODING_FOCUS.register(FakeFocus())

        _, grimoire = _cast(_one_call_ritual())

        finished = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        assert finished[0].result == {
            "session": "new",
            "key": None,
            "session_id": "s1",
            "num_turns": 2,
            "cost_usd": 0.5,
            "text": "all done",
        }


class TestResumedRites:
    @staticmethod
    def test_a_finished_call_comes_off_the_journal_instead_of_the_agent():
        focus = FakeFocus()
        CODING_FOCUS.register(focus)
        recorded = {
            "session": "new",
            "key": None,
            "session_id": "s9",
            "num_turns": 7,
            "cost_usd": 1.5,
            "text": "what it said last time",
        }

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("fix it"))

        result, _ = _cast(
            entry(target=work, payload=Answer(port=1)),
            ledger=journalled(recorded, name="coding"),
        )

        assert not focus.calls
        assert result == CodingResult(
            text="what it said last time", session_id="s9", num_turns=7, cost_usd=1.5
        )

    # The thread is filed as if the call had happened, so the next one on it
    # resumes the session the interrupted cast had already opened.
    @staticmethod
    def test_a_replayed_call_still_files_its_session():
        focus = FakeFocus()
        CODING_FOCUS.register(focus)

        @step
        async def work(_: Answer) -> Transition:
            await coding("first")
            return done(await coding("second", session=Session.CONTINUE))

        recorded = {"session": "new", "key": None, "session_id": "s9", "text": "done"}

        _cast(
            entry(target=work, payload=Answer(port=1)),
            ledger=journalled(recorded, name="coding"),
        )

        assert [call.resume for call in focus.calls] == ["s9"]

    @staticmethod
    def test_a_typed_return_is_validated_out_of_the_recorded_text():
        CODING_FOCUS.register(FakeFocus())

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("port?", output=Answer))

        recorded = {"session": "new", "text": '{"port": 8080}'}

        result, _ = _cast(
            entry(target=work, payload=Answer(port=1)),
            ledger=journalled(recorded, name="coding"),
        )

        assert result == Answer(port=8080)

    @staticmethod
    def test_a_journal_holding_something_else_says_so():
        CODING_FOCUS.register(FakeFocus())

        with pytest.raises(CodingOutputError, match="journaled as something else"):
            _cast(
                _one_call_ritual(),
                ledger=journalled("not a reply at all", name="coding"),
            )

    @staticmethod
    def test_a_rite_the_journal_does_not_know_is_run():
        focus = FakeFocus()
        CODING_FOCUS.register(focus)

        # The recorded rite was a `shell`, so this coding rite matches nothing
        # and the ledger is spent rather than misread.
        _cast(_one_call_ritual(), ledger=journalled({"text": "x"}, name="shell"))

        assert len(focus.calls) == 1

    # A rite that failed is not a rite that is done, and a resume that replayed
    # its result would carry an error forward as if it had succeeded.
    @staticmethod
    def test_a_rite_that_failed_is_run_again():
        focus = FakeFocus()
        CODING_FOCUS.register(focus)

        recorded = {"session": "new", "text": "what failed"}

        _cast(
            _one_call_ritual(),
            ledger=journalled(recorded, name="coding", status="error"),
        )

        assert len(focus.calls) == 1

    # Nothing is asked of the agent, so nothing needs the SDK that answers for
    # it: a cast interrupted on one machine can be resumed on another.
    @staticmethod
    def test_a_replayed_rite_needs_no_focus_at_all():
        register()
        recorded = {"session": "new", "text": "what it said last time"}

        @step
        async def work(_: Answer) -> Transition:
            return done(await coding("fix it"))

        result, _ = _cast(
            entry(target=work, payload=Answer(port=1)),
            ledger=journalled(recorded, name="coding"),
        )

        assert result == CodingResult(text="what it said last time")
