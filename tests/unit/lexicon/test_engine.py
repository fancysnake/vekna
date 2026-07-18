import asyncio
import io
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Goto,
    Grimoire,
    StandaloneRenderer,
    Transition,
    WorkflowBudgetExceededError,
    done,
    goto,
    ritual,
    run_cast,
    step,
)
from vekna.wire import RiteDelta, RiteFinished, RiteStarted


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
        started = [event for event in grimoire.events if isinstance(event, RiteStarted)]
        assert len(started) == start + 1
        assert {event.name for event in started} == {"tick"}

    @staticmethod
    def test_budget_exceeded_raises():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        with pytest.raises(WorkflowBudgetExceededError):
            asyncio.run(
                run_cast(
                    ritual=spinner,
                    components=spinner.components(start=1),
                    grimoire=grimoire,
                    channel=_channel(),
                )
            )


class TestGrimoire:
    @staticmethod
    def test_on_event_fires_live_in_order():
        seen = []
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock, on_event=seen.append)

        rite_id = grimoire.rite_started(name="fix")
        grimoire.rite_delta(rite_id, "working...")
        grimoire.rite_finished(rite_id, result={"session_id": "s1"})

        assert [type(event) for event in seen] == [RiteStarted, RiteDelta, RiteFinished]
        assert seen == grimoire.events

    @staticmethod
    def test_rite_finished_carries_result():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)

        rite_id = grimoire.rite_started(name="fix")
        grimoire.rite_finished(rite_id, result={"cost": 1})

        finished = grimoire.events[-1]
        assert isinstance(finished, RiteFinished)
        assert finished.result == {"cost": 1}
