import asyncio
import io
from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    RitualError,
    Transition,
    current_rite,
    done,
    emit_delta,
    goto,
    medium,
    ritual,
    step,
)
from vekna.lexicon._links import StandaloneRenderer
from vekna.lexicon._mills import Grimoire, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteStreamed


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


@medium
async def whoami() -> None:
    await asyncio.sleep(0)
    emit_delta("here")


@step
async def identify(_state: Start) -> Transition:
    await whoami()
    return done(None)


@ritual("identifier")
async def identifier() -> Transition:
    await asyncio.sleep(0)
    return goto(identify, Start())


# The ritual body itself runs at the cast root, outside any rite.
@ritual("rootless")
async def rootless() -> Transition:
    await asyncio.sleep(0)
    emit_delta("nowhere to hang")
    return done(None)


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

        started = [e for e in grimoire.events if isinstance(e, RiteBegan)]
        step_rite = next(e for e in started if e.name == "choose")
        medium_rite = next(e for e in started if e.name == "pick")
        assert medium_rite.category == "medium"
        assert medium_rite.parent_id == step_rite.rite_id

    @staticmethod
    def test_a_decorated_medium_introspects_as_itself():
        assert whoami.__name__ == "whoami"

    @staticmethod
    def test_current_rite_outside_cast_raises():
        with pytest.raises(RitualError):
            current_rite()


class TestEmitDelta:
    @staticmethod
    def test_inside_a_medium_it_hangs_off_the_medium_rite():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())

        asyncio.run(
            run_cast(
                ritual=identifier,
                components=identifier.components(),
                grimoire=grimoire,
                channel=renderer,
            )
        )

        started = [e for e in grimoire.events if isinstance(e, RiteBegan)]
        medium_rite = next(e for e in started if e.name == "whoami")
        delta = next(e for e in grimoire.events if isinstance(e, RiteStreamed))
        assert (delta.rite_id, delta.delta) == (medium_rite.rite_id, "here")

    @staticmethod
    def test_at_the_cast_root_it_raises():
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
        renderer = StandaloneRenderer(out=io.StringIO(), inp=io.StringIO())

        with pytest.raises(RitualError, match="no rite is running"):
            asyncio.run(
                run_cast(
                    ritual=rootless,
                    components=rootless.components(),
                    grimoire=grimoire,
                    channel=renderer,
                )
            )
