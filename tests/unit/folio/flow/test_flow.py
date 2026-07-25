import asyncio
import io
from datetime import datetime, timezone

from pydantic import BaseModel

from vekna.folio.flow import decide
from vekna.lexicon import Transition, done, goto, ritual, step
from vekna.lexicon.entry import Grimoire, StandaloneRenderer, run_cast


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


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


@ritual("survey")
async def survey() -> Transition:
    await asyncio.sleep(0)
    return goto(gather, State())


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
