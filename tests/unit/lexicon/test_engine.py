import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from tests.conftest import entry
from vekna.lexicon import (
    Done,
    Failure,
    FocusMissingError,
    NoComponents,
    RitualBoundaryError,
    RitualDefinitionError,
    RitualError,
    StepBoundaryError,
    StepBudgetExceededError,
    UnattendedPromptError,
    current_rite,
    medium,
    ritual,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer, UnattendedChannel
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


class Spun(BaseModel):
    left: int


class Last(BaseModel):
    left: int


class Fuse(BaseModel):
    pass


class Charge(BaseModel):
    pass


class Noted(BaseModel):
    left: int


class Lost(BaseModel):
    pass


@step
def tick(state: Tick) -> Tick | Done[Tick]:
    if not state.left:
        return Done(state)
    return Tick(left=state.left - 1)


@ritual("countdown")
def countdown(components: Start) -> Tick:
    return Tick(left=components.start)


@step
def spin(state: Spun) -> Spun:
    return state


@ritual("spinner", max_steps=5)
def spinner(components: Start) -> Spun:
    return Spun(left=components.start)


@step
def finish(state: Last) -> Done[Last]:
    return Done(state)


_SPRINT_START = 7


@ritual("sprint", max_steps=1)
def sprint(components: Start) -> Last:
    return Last(left=components.start)


class BoomError(RuntimeError):
    pass


@step
def explode(_state: Charge) -> Done[None]:
    raise BoomError


@ritual("detonate")
def detonate(_: NoComponents) -> Charge:
    return Charge()


@medium
async def combust() -> None:
    await asyncio.sleep(0)
    raise BoomError


@step
async def light_fuse(_state: Fuse) -> Done[None]:
    await combust()
    return Done(None)


@ritual("smoulder")
def smoulder(_: NoComponents) -> Fuse:
    return Fuse()


class TestRitual:
    @staticmethod
    def test_takes_the_declared_components_model():
        assert countdown.components is Start

    @staticmethod
    def test_fires_opening_transition_to_first_step():
        opening = asyncio.run(countdown.run(countdown.components(start=2)))

        assert opening == Tick(left=2)
        assert (countdown.exits, countdown.ends) == ((Tick,), False)

    @staticmethod
    def test_components_of_another_ritual_do_not_pass_the_boundary():
        with pytest.raises(RitualBoundaryError, match="expected Start, got Tick"):
            asyncio.run(countdown.run(Tick(left=2)))


class TestRitualDefinition:
    @staticmethod
    def test_a_ritual_without_components_is_rejected():
        with pytest.raises(RitualDefinitionError, match="exactly one"):

            @ritual("bare")
            def bare() -> Done[None]:
                return Done(None)

    @staticmethod
    def test_a_ritual_with_two_parameters_is_rejected():
        with pytest.raises(RitualDefinitionError, match="exactly one"):

            @ritual("pair")
            def pair(components: Start, extra: Tick) -> Done[Start]:
                return Done(Start(start=components.start + extra.left))

    @staticmethod
    def test_components_must_be_a_pydantic_model():
        with pytest.raises(RitualDefinitionError, match="pydantic model"):

            @ritual("loose")
            def loose(bound: int) -> Done[Start]:
                return Done(Start(start=bound))

    @staticmethod
    def test_a_name_holding_the_namespace_separator_is_rejected():
        with pytest.raises(RitualDefinitionError, match="'cabinet:review'"):
            ritual("cabinet:review")


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

        assert result == Last(left=_SPRINT_START)

    # Routed by the class of the value, not by anything the step said about
    # itself: a payload nothing takes stops the cast at the boundary. Built by
    # hand, because a decorated ritual could not declare it without lying to
    # mypy.
    @staticmethod
    def test_a_transition_no_step_takes_is_a_boundary_error():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        wandering = entry(payload=Lost())

        with pytest.raises(StepBoundaryError, match="no step takes Lost"):
            asyncio.run(
                run_cast(
                    ritual=wandering,
                    components=wandering.components(),
                    grimoire=grimoire,
                    channel=_channel(),
                )
            )

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

        assert [(e.rite_id, e.status, e.error) for e in finished] == [
            ("r1", "error", "BoomError")
        ]

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

        assert "✗ explode  — BoomError" in out.getvalue()


class Attempt(BaseModel):
    left: int


class Report(BaseModel):
    attempts: int
    message: str


@step
def attempt(state: Attempt) -> Done[Attempt]:
    if state.left:
        msg = f"{state.left} left"
        raise BoomError(msg)
    return Done(state)


_GIVE_UP = 3


@step
def triage(failure: Failure[Attempt]) -> Attempt | Done[Report]:
    if failure.attempt >= _GIVE_UP:
        return Done(Report(attempts=failure.attempt, message=failure.error.message))
    return Attempt(left=failure.payload.left - 1)


@ritual("retry")
def retry(components: Attempt) -> Attempt:
    return components


class Probe(BaseModel):
    tag: str


@step
def probe(_: Probe) -> Done[None]:
    msg = "probe broke"
    raise BoomError(msg)


@step
def caught(failure: Failure[Probe]) -> Done[Failure[Probe]]:
    return Done(failure)


class Fragile(BaseModel):
    pass


@step
def fragile(_: Fragile) -> Done[None]:
    msg = "first"
    raise BoomError(msg)


@step
def mend(_: Failure[Fragile]) -> Done[None]:
    msg = "second"
    raise BoomError(msg)


class Stubborn(BaseModel):
    pass


_STUBBORN_VISITS = 3


@step(max_visits=_STUBBORN_VISITS)
def stubborn(_: Stubborn) -> Done[None]:
    raise BoomError


@step
def again(failure: Failure[Stubborn]) -> Stubborn:
    return failure.payload


class Ask(BaseModel):
    pass


@step
async def ask(_: Ask) -> Done[None]:
    await current_rite().channel.decide(prompt="merge #74 now?")
    return Done(None)


@step
def unasked(failure: Failure[Ask]) -> Done[Report]:
    return Done(Report(attempts=failure.attempt, message=failure.error.message))


def _cast(the_step_payload: BaseModel, *, channel=None) -> tuple[object, Grimoire]:
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    the_ritual = entry(payload=the_step_payload)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=channel or _channel(),
        )
    )
    return result, grimoire


class TestFailureRouting:
    @staticmethod
    def test_a_raise_routes_to_the_step_taking_its_failure():
        result, _ = _cast(Probe(tag="x"))

        assert isinstance(result, Failure)
        assert result.payload == Probe(tag="x")
        assert (result.rite.rite_id, result.rite.step) == ("r1", "probe")
        assert (result.error.type, result.error.message) == ("BoomError", "probe broke")
        assert "probe broke" in result.error.traceback
        assert result.attempt == 1

    @staticmethod
    def test_a_narrowed_retry_runs_the_step_again_until_it_holds():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        result = asyncio.run(
            run_cast(
                ritual=retry,
                components=Attempt(left=2),
                grimoire=grimoire,
                channel=_channel(),
            )
        )

        assert result == Attempt(left=0)
        ended = [e for e in grimoire.events if isinstance(e, RiteEnded)]
        assert [(e.status, e.error) for e in ended] == [
            ("error", "2 left"),
            ("ok", None),
            ("error", "1 left"),
            ("ok", None),
            ("ok", None),
        ]

    @staticmethod
    def test_attempt_counts_every_failure_of_the_step_in_the_cast():
        result = asyncio.run(
            run_cast(
                ritual=retry,
                components=Attempt(left=9),
                grimoire=Grimoire(cast_id="c1", clock=_fixed_clock),
                channel=_channel(),
            )
        )

        assert result == Report(attempts=_GIVE_UP, message="7 left")

    # What entered `mend` was a `Failure[Fragile]`, which nothing takes the
    # failure of, so its raise is the cast's.
    @staticmethod
    def test_a_recovery_step_that_raises_is_not_caught_by_itself():
        with pytest.raises(BoomError, match="second"):
            _cast(Fragile())

    @staticmethod
    def test_a_retry_that_never_converges_stops_on_max_visits():
        with pytest.raises(
            StepBudgetExceededError, match="'stubborn' exceeded max_visits=3"
        ):
            _cast(Stubborn())

    @staticmethod
    def test_a_refused_prompt_routes_like_any_failure():
        result, _ = _cast(Ask(), channel=UnattendedChannel())

        assert result == Report(
            attempts=1, message="unattended cast refused to ask: merge #74 now?"
        )

    @staticmethod
    def test_the_unattended_channel_names_the_prompt_it_refused():
        with pytest.raises(UnattendedPromptError, match="merge #74 now\\?"):
            asyncio.run(UnattendedChannel().decide(prompt="merge #74 now?"))

    @staticmethod
    def test_max_visits_below_one_is_refused():
        with pytest.raises(RitualDefinitionError, match="at least 1, got 0"):
            step(max_visits=0)


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

    # Two trials in one TaskGroup hold overlapping scopes and exit in whichever
    # order they finish. Saving and restoring one attribute is only correct
    # while the blocks nest: the first to leave would put the other's focus
    # back, and the survivor would answer with a focus that had already gone.
    @staticmethod
    def test_overlapping_scopes_each_keep_their_own_focus():
        slot = FocusSlot[str]("shell")
        slot.register("the author's own")

        async def scoped(focus: str, hold: float) -> list[str]:
            with slot.scope(focus):
                seen = [slot.resolve()]
                await asyncio.sleep(hold)
                seen.append(slot.resolve())
            return seen

        async def both() -> list[list[str]]:
            async with asyncio.TaskGroup() as group:
                first = group.create_task(scoped("the first double", 0.02))
                second = group.create_task(scoped("the second double", 0.0))
            return [first.result(), second.result()]

        assert asyncio.run(both()) == [
            ["the first double", "the first double"],
            ["the second double", "the second double"],
        ]
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
        def note(state: Noted) -> Noted | Done[Noted]:
            book = current_rite().sessions
            seen.append((book, book.named("thread")))
            book.record(f"s{state.left}", name="thread")
            if not state.left:
                return Done(state)
            return Noted(left=state.left - 1)

        @ritual("noting")
        def noting(components: Start) -> Noted:
            return Noted(left=components.start)

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
