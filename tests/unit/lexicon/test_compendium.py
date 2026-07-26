import asyncio

import pytest
from pydantic import BaseModel

from vekna.lexicon import RitualDefinitionError, Transition, done, goto, ritual, step
from vekna.lexicon._mills.engine import Compendium


class State(BaseModel):
    x: int


@step
async def noop(state: State) -> Transition:
    await asyncio.sleep(0)
    return done(state)


@ritual("alpha")
async def alpha(x: int) -> Transition:
    await asyncio.sleep(0)
    return goto(noop, State(x=x))


@ritual("beta")
async def beta(x: int) -> Transition:
    await asyncio.sleep(0)
    return goto(noop, State(x=x))


class TestCompendium:
    @staticmethod
    def test_register_and_lookup():
        compendium = Compendium()
        compendium.register(alpha)
        compendium.register(beta)

        assert compendium.ritual("alpha") is alpha
        assert compendium.names() == ["alpha", "beta"]

    @staticmethod
    def test_duplicate_registration_raises():
        compendium = Compendium()
        compendium.register(alpha)

        with pytest.raises(RitualDefinitionError):
            compendium.register(alpha)

    @staticmethod
    def test_missing_ritual_raises():
        compendium = Compendium()

        with pytest.raises(RitualDefinitionError):
            compendium.ritual("nope")

    @staticmethod
    def test_registered_step_is_looked_up_by_name():
        compendium = Compendium()
        compendium.register_step(noop)

        assert compendium.step("noop") is noop

    @staticmethod
    def test_unregistered_step_is_none():
        assert Compendium().step("noop") is None
