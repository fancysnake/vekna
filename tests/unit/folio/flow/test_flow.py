import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from tests.conftest import entry, journalled
from vekna.folio.flow import decide
from vekna.lexicon import RitualError, Transition, done, step
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


class State(BaseModel):
    pass


class Survey(BaseModel):
    choice: str
    approved: bool
    note: str


@step
async def gather(_state: State) -> Transition:
    choice = await decide("pick", options=["x", "y"])
    approved = await decide("ok?")
    note = await decide("note?", free=True)
    return done(Survey(choice=choice, approved=approved, note=note))


survey = entry(name="survey", target=gather, payload=State())


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


@step
async def choose(_state: State) -> Transition:
    return done(Choice(picked=await decide("pick", options=["fix", "file"])))


picker = entry(name="picker", target=choose, payload=State())


def _resumed(recorded: str) -> object:
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
    return asyncio.run(
        run_cast(
            ritual=picker,
            components=picker.components(),
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
