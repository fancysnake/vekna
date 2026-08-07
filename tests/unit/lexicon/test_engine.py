import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    FocusMissingError,
    Goto,
    NoComponents,
    RitualBoundaryError,
    RitualDefinitionError,
    RitualError,
    StepBudgetExceededError,
    Transition,
    current_rite,
    done,
    goto,
    medium,
    ritual,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import (
    FocusSlot,
    Grimoire,
    SessionBook,
    offer_prompt,
    prompt_runner,
    run_cast,
)
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _channel() -> StandaloneRenderer:
    return StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())


class Tick(BaseModel):
    left: int


class Start(BaseModel):
    start: int


@step
def tick(state: Tick) -> Transition:
    if not state.left:
        return done(state)
    return goto(tick, Tick(left=state.left - 1))


@ritual("countdown")
def countdown(components: Start) -> Transition:
    return goto(tick, Tick(left=components.start))


@step
def spin(state: Tick) -> Transition:
    return goto(spin, state)


@ritual("spinner", max_steps=5)
def spinner(components: Start) -> Transition:
    return goto(spin, Tick(left=components.start))


@step
def finish(state: Tick) -> Transition:
    return done(state)


_SPRINT_START = 7


@ritual("sprint", max_steps=1)
def sprint(components: Start) -> Transition:
    return goto(finish, Tick(left=components.start))


class BoomError(RuntimeError):
    pass


@step
def explode(_state: Tick) -> Transition:
    raise BoomError


@ritual("detonate")
def detonate(_: NoComponents) -> Transition:
    return goto(explode, Tick(left=0))


@medium
async def combust() -> None:
    await asyncio.sleep(0)
    raise BoomError


@step
async def light_fuse(_state: Tick) -> Transition:
    await combust()
    return done(None)


@ritual("smoulder")
def smoulder(_: NoComponents) -> Transition:
    return goto(light_fuse, Tick(left=0))


class TestRitual:
    @staticmethod
    def test_takes_the_declared_components_model():
        assert countdown.components is Start

    @staticmethod
    def test_fires_opening_transition_to_first_step():
        opening = asyncio.run(countdown.run(countdown.components(start=2)))

        assert isinstance(opening, Goto)
        assert opening.target is tick

    @staticmethod
    def test_components_of_another_ritual_do_not_pass_the_boundary():
        with pytest.raises(RitualBoundaryError, match="expected Start, got Tick"):
            asyncio.run(countdown.run(Tick(left=2)))


class TestRitualDefinition:
    @staticmethod
    def test_a_ritual_without_components_is_rejected():
        with pytest.raises(RitualDefinitionError, match="exactly one"):

            @ritual("bare")
            def bare() -> Transition:
                return done()

    @staticmethod
    def test_a_ritual_with_two_parameters_is_rejected():
        with pytest.raises(RitualDefinitionError, match="exactly one"):

            @ritual("pair")
            def pair(components: Start, extra: Tick) -> Transition:
                return done(components.start + extra.left)

    @staticmethod
    def test_components_must_be_a_pydantic_model():
        with pytest.raises(RitualDefinitionError, match="pydantic model"):

            @ritual("loose")
            def loose(bound: int) -> Transition:
                return done(bound)


class TestRunCast:
    @staticmethod
    def test_trampolines_until_done():
        start = 3
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        result = asyncio.run(
            run_cast(
                ritual=countdown,
                components=countdown.components(start=start),
                grimoire=grimoire,
                channel=_channel(),
            )
        )

        assert result == Tick(left=0)
        started = [event for event in grimoire.events if isinstance(event, RiteBegan)]
        assert len(started) == start + 1
        assert {event.name for event in started} == {"tick"}

    @staticmethod
    def test_returns_result_of_the_last_affordable_step():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        result = asyncio.run(
            run_cast(
                ritual=sprint,
                components=sprint.components(start=_SPRINT_START),
                grimoire=grimoire,
                channel=_channel(),
            )
        )

        assert result == Tick(left=_SPRINT_START)

    @staticmethod
    def test_budget_exceeded_raises():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        with pytest.raises(StepBudgetExceededError):
            asyncio.run(
                run_cast(
                    ritual=spinner,
                    components=spinner.components(start=1),
                    grimoire=grimoire,
                    channel=_channel(),
                )
            )


class TestFailedRiteIsJournaled:
    @staticmethod
    def _cast(the_ritual) -> Grimoire:
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        with pytest.raises(BoomError):
            asyncio.run(
                run_cast(
                    ritual=the_ritual,
                    components=the_ritual.components(),
                    grimoire=grimoire,
                    channel=_channel(),
                )
            )
        return grimoire

    @staticmethod
    def _finished(grimoire: Grimoire) -> list[RiteEnded]:
        return [e for e in grimoire.events if isinstance(e, RiteEnded)]

    @classmethod
    def test_a_step_that_raises_still_closes_its_rite(cls):
        finished = cls._finished(cls._cast(detonate))

        assert [(e.rite_id, e.status) for e in finished] == [("r1", "error")]

    @classmethod
    def test_a_medium_that_raises_is_not_journaled_as_success(cls):
        finished = cls._finished(cls._cast(smoulder))

        # The medium closes first, then the step it brought down with it.
        assert [(e.rite_id, e.status) for e in finished] == [
            ("r2", "error"),
            ("r1", "error"),
        ]

    @classmethod
    def test_renderer_marks_a_failed_rite(cls):
        out = io.StringIO()
        renderer = StandaloneRenderer(out=out, inp=io.StringIO())
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock, on_event=renderer.render)
        with pytest.raises(BoomError):
            asyncio.run(
                run_cast(
                    ritual=detonate,
                    components=detonate.components(),
                    grimoire=grimoire,
                    channel=renderer,
                )
            )

        assert "✗ explode" in out.getvalue()


class TestFocusSlot:
    @staticmethod
    def test_a_registered_focus_resolves():
        slot = FocusSlot[str]("shell")
        slot.register("the focus")

        assert slot.resolve() == "the focus"

    @staticmethod
    def test_an_unexpected_medium_names_itself_and_nothing_more():
        slot = FocusSlot[str]("unheard")

        with pytest.raises(FocusMissingError, match="unheard") as raised:
            slot.resolve()

        # No hint was ever expected for it, so the message is the bare one.
        assert "—" not in str(raised.value)

    @staticmethod
    def test_nothing_registered_and_no_default_is_an_error():
        slot = FocusSlot[str]("coding")
        slot.expect(hint="pip install claude-agent-sdk")

        with pytest.raises(FocusMissingError, match="pip install claude-agent-sdk"):
            slot.resolve()

    @staticmethod
    def test_a_default_answers_when_nothing_is_registered():
        slot = FocusSlot[str]("shell")

        assert slot.resolve(default="bash") == "bash"

    @staticmethod
    def test_a_registered_focus_wins_over_the_default():
        slot = FocusSlot[str]("shell")
        slot.register("the double")

        assert slot.resolve(default="bash") == "the double"

    @staticmethod
    def test_a_cleared_slot_forgets_the_hint_as_well_as_the_focus():
        slot = FocusSlot[str]("coding")
        slot.expect(hint="pip install claude-agent-sdk")
        slot.register("the focus")

        slot.clear()

        with pytest.raises(FocusMissingError) as raised:
            slot.resolve()
        assert "pip install" not in str(raised.value)


class TestPrompts:
    @staticmethod
    def test_offered_prompt_comes_back():
        async def run(_prompt: str) -> str:
            await asyncio.sleep(0)
            return "answered"

        offer_prompt("scribing", run)

        assert prompt_runner("scribing") is run

    @staticmethod
    def test_a_medium_offering_no_prompt_is_an_error():
        with pytest.raises(RitualError, match="offers no one-shot prompt"):
            prompt_runner("hollow")


class TestFocusScope:
    @staticmethod
    def test_the_scoped_focus_answers_inside_the_block():
        slot = FocusSlot[str]("shell")

        with slot.scope("the double"):
            resolved = slot.resolve()

        assert resolved == "the double"

    @staticmethod
    def test_an_absent_focus_is_absent_again_afterwards():
        slot = FocusSlot[str]("shell")

        with slot.scope("the double"):
            pass

        with pytest.raises(FocusMissingError, match="no Focus registered"):
            slot.resolve()

    @staticmethod
    def test_a_focus_registered_before_the_scope_comes_back():
        slot = FocusSlot[str]("shell")
        slot.register("the author's own")

        with slot.scope("the double"):
            pass

        assert slot.resolve() == "the author's own"

    @staticmethod
    def test_a_scope_whose_block_raises_still_restores():
        slot = FocusSlot[str]("shell")
        slot.register("the author's own")

        with pytest.raises(RuntimeError), slot.scope("the double"):
            raise RuntimeError

        assert slot.resolve() == "the author's own"


class TestSessionBook:
    @staticmethod
    def test_an_unrecorded_name_resolves_to_nothing():
        book = SessionBook()

        assert book.named("lint-loop") is None
        assert book.latest is None

    @staticmethod
    def test_a_named_record_reads_back_by_name_and_moves_latest():
        book = SessionBook()

        book.record("s1", name="lint-loop")

        assert book.named("lint-loop") == "s1"
        assert book.latest == "s1"

    @staticmethod
    def test_an_unnamed_record_moves_latest_and_names_nothing():
        book = SessionBook()

        book.record("s1")

        assert book.latest == "s1"
        assert book.named("s1") is None

    @staticmethod
    def test_two_threads_keep_their_own_ids():
        book = SessionBook()

        book.record("s1", name="review")
        book.record("s2", name="repair")

        assert book.named("review") == "s1"
        assert book.named("repair") == "s2"
        assert book.latest == "s2"

    @staticmethod
    def test_one_book_spans_every_rite_of_a_cast_and_no_further():
        seen = []

        @step
        def note(state: Tick) -> Transition:
            book = current_rite().sessions
            seen.append((book, book.named("thread")))
            book.record(f"s{state.left}", name="thread")
            if not state.left:
                return done(state)
            return goto(note, Tick(left=state.left - 1))

        @ritual("noting")
        def noting(components: Start) -> Transition:
            return goto(note, Tick(left=components.start))

        for _ in range(2):
            asyncio.run(
                run_cast(
                    ritual=noting,
                    components=noting.components(start=1),
                    grimoire=Grimoire(cast_id="c1", clock=_fixed_clock),
                    channel=_channel(),
                )
            )

        books = [book for book, _ in seen]
        reads = [read for _, read in seen]
        assert books[1] is books[0]
        assert books[2] is not books[0]
        assert reads == [None, "s1", None, "s1"]


class TestGrimoire:
    @staticmethod
    def test_on_event_fires_live_in_order():
        seen = []
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock, on_event=seen.append)

        rite_id = grimoire.rite_started(name="fix")
        grimoire.rite_delta(rite_id, "working...")
        grimoire.rite_finished(rite_id, result={"session_id": "s1"})

        assert [type(event) for event in seen] == [RiteBegan, RiteStreamed, RiteEnded]
        assert seen == grimoire.events

    @staticmethod
    def test_rite_finished_carries_result():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        rite_id = grimoire.rite_started(name="fix")
        grimoire.rite_finished(rite_id, result={"cost": 1})

        finished = grimoire.events[-1]
        assert isinstance(finished, RiteEnded)
        assert finished.result == {"cost": 1}
