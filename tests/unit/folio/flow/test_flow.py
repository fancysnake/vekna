import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, JsonValue

from tests.conftest import entry, journalled
from vekna.folio.flow import decide, race
from vekna.lexicon import Done, MediumBoundaryError, RitualError, medium, step
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteEnded, Ritual


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


class Gathering(BaseModel):
    pass


class Survey(BaseModel):
    choice: str
    approved: bool
    note: str


@step
async def gather(_state: Gathering) -> Done[Survey]:
    choice = await decide("pick", options=["x", "y"])
    approved = await decide("ok?")
    note = await decide("note?", free=True)
    return Done(Survey(choice=choice, approved=approved, note=note))


survey = entry(name="survey", payload=Gathering())


class TestDecideMedium:
    @staticmethod
    def test_choice_confirm_free_round_trip_via_stdin():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(
            out=io.StringIO(), inp=io.StringIO("y\nyes\nhello\n")
        )

        result = asyncio.run(
            run_cast(
                ritual=survey,
                components=survey.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        assert result == Survey(choice="y", approved=True, note="hello")


class Choice(BaseModel):
    picked: str


class Choosing(BaseModel):
    pass


@step
async def choose(_state: Choosing) -> Done[Choice]:
    return Done(Choice(picked=await decide("pick", options=["fix", "file"])))


picker = entry(name="picker", payload=Choosing())


class Verdict(BaseModel):
    agreed: bool


class Confirming(BaseModel):
    pass


@step
async def confirm(_state: Confirming) -> Done[Verdict]:
    return Done(Verdict(agreed=await decide("ok?")))


confirmer = entry(name="confirmer", payload=Confirming())


class Emptying(BaseModel):
    pass


@step
async def choose_nothing(_state: Emptying) -> Done[Choice]:
    nothing: list[str] = []
    return Done(Choice(picked=await decide("pick", options=nothing)))


emptier = entry(name="emptier", payload=Emptying())


class Note(BaseModel):
    text: str


class Jotting(BaseModel):
    pass


@step
async def jot(_state: Jotting) -> Done[Note]:
    return Done(Note(text=await decide("note?", free=True)))


jotter = entry(name="jotter", payload=Jotting())


def _resumed(recorded: JsonValue, ritual: Ritual = picker) -> object:
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    return asyncio.run(
        run_cast(
            ritual=ritual,
            components=ritual.components(),
            grimoire=grimoire,
            channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
            ledger=journalled(recorded, name="decide"),
        )
    )


class TestResumedDecisions:
    # There is no stdin to answer from here: the answer can only have come off
    # the journal.
    @staticmethod
    def test_a_question_already_answered_is_not_asked_again():
        assert _resumed("fix") == Choice(picked="fix")

    # The options a ritual offers are what its own `Literal` promises the
    # caller. An answer recorded before they changed is not one of them.
    @staticmethod
    def test_an_answer_outside_the_options_is_refused():
        with pytest.raises(RitualError, match="'ignore' is not one of: fix, file"):
            _resumed("ignore")

    @staticmethod
    def test_a_bare_decision_comes_back_as_the_truth_it_was_recorded_as():
        assert _resumed("yes", confirmer) == Verdict(agreed=True)

    # A bare `decide` is read for truth, so anything but yes or no would come
    # back `False` — a recorded yes answered as a no with nothing to show for
    # it. This is the one refusal that stops a wrong answer rather than a
    # missing one.
    @staticmethod
    def test_a_bare_decision_recorded_as_neither_is_refused():
        with pytest.raises(RitualError, match="'maybe' is not one of: yes, no"):
            _resumed("maybe", confirmer)

    # Free text is the case with nothing to check against: whatever was typed
    # is the answer, and "maybe" is a perfectly good one.
    @staticmethod
    def test_free_text_is_taken_as_it_was_recorded():
        assert _resumed("maybe", jotter) == Note(text="maybe")

    @staticmethod
    def test_an_answer_that_is_not_text_is_refused():
        with pytest.raises(RitualError, match="answer 3 is not text"):
            _resumed(3, jotter)


class TestEmptyOptions:
    # A question with nothing to pick from is a bug in the step. Left alone it
    # would fall through to yes/no live and then be refused off the journal on
    # resume, so it stops at the medium instead.
    @staticmethod
    def test_offering_no_options_is_refused():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        with pytest.raises(MediumBoundaryError, match="at least one option"):
            asyncio.run(
                run_cast(
                    ritual=emptier,
                    components=emptier.components(),
                    grimoire=grimoire,
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                )
            )


@medium
async def runner(label: str, *, seconds: float, fails: bool = False) -> str:
    await asyncio.sleep(seconds)
    if fails:
        msg = f"{label} fell"
        raise RitualError(msg)
    return label


class Racing(BaseModel):
    pass


class Stumbling(BaseModel):
    pass


class Unentered(BaseModel):
    pass


class Falling(BaseModel):
    pass


@step
async def racing(_: Racing) -> Done[Note]:
    return Done(
        Note(text=await race(runner("slow", seconds=60), runner("fast", seconds=0)))
    )


@step
async def stumbling(_: Stumbling) -> Done[Note]:
    return Done(
        Note(
            text=await race(
                runner("early", seconds=0, fails=True), runner("late", seconds=0.01)
            )
        )
    )


@step
async def falling(_: Falling) -> Done[Note]:
    return Done(
        Note(
            text=await race(
                runner("one", seconds=0, fails=True),
                runner("two", seconds=0, fails=True),
            )
        )
    )


class Tied(BaseModel):
    pass


@step
async def tied(_: Tied) -> Done[Note]:
    return Done(
        Note(text=await race(runner("first", seconds=0), runner("second", seconds=0)))
    )


@step
async def empty_race(_: Unentered) -> Done[Note]:
    return Done(Note(text=await race()))


def _raced(payload: BaseModel) -> tuple[BaseModel | None, Grimoire]:
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    the_ritual = entry(payload=payload)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
        )
    )
    return result, grimoire


def _ended(grimoire: Grimoire) -> dict[str, str]:
    summaries = {
        event.rite_id: event.summary
        for event in grimoire.events
        if isinstance(event, RiteBegan) and event.category == "medium"
    }
    return {
        str(summaries[event.rite_id]): event.status
        for event in grimoire.events
        if isinstance(event, RiteEnded) and event.rite_id in summaries
    }


class TestRace:
    @staticmethod
    def test_the_first_to_finish_wins_and_the_rest_are_cancelled():
        result, grimoire = _raced(Racing())

        assert result == Note(text="fast")
        assert _ended(grimoire) == {"fast": "ok", "slow": "cancelled"}

    @staticmethod
    def test_an_entrant_that_raises_first_does_not_lose_the_race():
        result, grimoire = _raced(Stumbling())

        assert result == Note(text="late")
        assert _ended(grimoire) == {"early": "error", "late": "ok"}

    @staticmethod
    def test_when_every_entrant_raises_the_race_fails_naming_each():
        with pytest.raises(
            RitualError,
            match=(
                r"every entrant in the race failed — "
                r"RitualError: one fell; RitualError: two fell"
            ),
        ):
            _raced(Falling())

    # Both end in the same round, so neither finished first.
    @staticmethod
    def test_a_tie_goes_to_the_entrant_passed_first():
        result, _ = _raced(Tied())

        assert result == Note(text="first")

    @staticmethod
    def test_a_race_with_no_entrants_is_refused():
        with pytest.raises(MediumBoundaryError, match="at least one entrant"):
            _raced(Unentered())


async def _gives_up() -> str:
    await asyncio.sleep(0)
    raise asyncio.CancelledError


class Abandoning(BaseModel):
    pass


@step
async def abandoning(_: Abandoning) -> Done[Note]:
    return Done(Note(text=await race(_gives_up(), runner("stayed", seconds=0.01))))


class TestRaceAbandoned:
    @staticmethod
    def test_an_entrant_cancelled_on_its_own_drops_out():
        result, _ = _raced(Abandoning())

        assert result == Note(text="stayed")
