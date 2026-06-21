import asyncio
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Goto,
    Grimoire,
    Transition,
    WorkflowBudgetExceededError,
    done,
    goto,
    ritual,
    run_cast,
    step,
)
from vekna.wire import RiteStarted


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


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
                )
            )
