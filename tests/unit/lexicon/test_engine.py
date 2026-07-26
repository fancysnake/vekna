import asyncio
import io
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Goto,
    StepBudgetExceededError,
    Transition,
    done,
    goto,
    medium,
    ritual,
    step,
)
from vekna.lexicon._links import StandaloneRenderer
from vekna.lexicon._mills import Grimoire, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteEnded, RiteStreamed


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _channel() -> StandaloneRenderer:
    return StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())


class Tick(BaseModel):
    left: int


@step
async def tick(state: Tick) -> Transition:
    await asyncio.sleep(0)
    if not state.left:
        return done(state)
    return goto(tick, Tick(left=state.left - 1))


@ritual("countdown")
async def countdown(start: int) -> Transition:
    await asyncio.sleep(0)
    return goto(tick, Tick(left=start))


@step
async def spin(state: Tick) -> Transition:
    await asyncio.sleep(0)
    return goto(spin, state)


@ritual("spinner", max_steps=5)
async def spinner(start: int) -> Transition:
    await asyncio.sleep(0)
    return goto(spin, Tick(left=start))


@step
async def finish(state: Tick) -> Transition:
    await asyncio.sleep(0)
    return done(state.left)


_SPRINT_START = 7


@ritual("sprint", max_steps=1)
async def sprint(start: int) -> Transition:
    await asyncio.sleep(0)
    return goto(finish, Tick(left=start))


class BoomError(RuntimeError):
    pass


@step
async def explode(_state: Tick) -> Transition:
    await asyncio.sleep(0)
    raise BoomError


@ritual("detonate")
async def detonate() -> Transition:
    await asyncio.sleep(0)
    return goto(explode, Tick(left=0))


@medium
async def combust() -> None:
    await asyncio.sleep(0)
    raise BoomError


@step
async def light_fuse(_state: Tick) -> Transition:
    await combust()
    return done(None)  # pragma: no cover


@ritual("smoulder")
async def smoulder() -> Transition:
    await asyncio.sleep(0)
    return goto(light_fuse, Tick(left=0))


class TestRitual:
    @staticmethod
    def test_builds_component_model_from_signature():
        assert "start" in countdown.components.model_fields

    @staticmethod
    def test_fires_opening_transition_to_first_step():
        opening = asyncio.run(countdown.run(countdown.components(start=2)))

        assert isinstance(opening, Goto)
        assert opening.target is tick


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

        assert result == _SPRINT_START

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
