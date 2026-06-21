import asyncio
import io
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Grimoire,
    RitualError,
    StandaloneRenderer,
    Transition,
    current_rite,
    done,
    goto,
    medium,
    ritual,
    run_cast,
    step,
)
from vekna.wire import RiteStarted


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


@medium
async def pick(*, prompt: str, options: list[str]) -> str:
    return await current_rite().channel.decide(prompt=prompt, options=options)


class Start(BaseModel):
    pass


class Picked(BaseModel):
    choice: str


@step
async def choose(_state: Start) -> Transition:
    choice = await pick(prompt="which?", options=["a", "b"])
    return done(Picked(choice=choice))


@ritual("chooser")
async def chooser() -> Transition:
    await asyncio.sleep(0)
    return goto(choose, Start())


class TestMedium:
    @staticmethod
    def test_prompts_via_channel_and_returns_choice():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO("b\n"))

        result = asyncio.run(
            run_cast(
                ritual=chooser,
                components=chooser.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        assert result == Picked(choice="b")

    @staticmethod
    def test_medium_rite_nests_under_its_step():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO("a\n"))

        asyncio.run(
            run_cast(
                ritual=chooser,
                components=chooser.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        started = [e for e in grimoire.events if isinstance(e, RiteStarted)]
        step_rite = next(e for e in started if e.name == "choose")
        medium_rite = next(e for e in started if e.name == "pick")
        assert medium_rite.category == "medium"
        assert medium_rite.parent_id == step_rite.rite_id

    @staticmethod
    def test_current_rite_outside_cast_raises():
        with pytest.raises(RitualError):
            current_rite()
