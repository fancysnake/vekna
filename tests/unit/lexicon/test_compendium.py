import asyncio
from dataclasses import replace

import pytest
from pydantic import BaseModel

from vekna.lexicon import RitualDefinitionError, Transition, done, goto, ritual, step
from vekna.lexicon._mills.engine import Compendium


class State(BaseModel):
    x: int


@step
def noop(state: State) -> Transition:
    return done(state)


@ritual("alpha")
def alpha(components: State) -> Transition:
    return goto(noop, State(x=components.x))


@ritual("beta")
def beta(components: State) -> Transition:
    return goto(noop, State(x=components.x))


@ritual("alpha")
async def same_name_as_alpha(components: State) -> Transition:
    await asyncio.sleep(0)
    return done(State(x=components.x))


# What two submodules each declaring a step called `noop` hand the sweep: the
# same name on a different object.
same_name_as_noop = replace(noop, source="async def noop(): ...")


class TestCompendium:
    @staticmethod
    def test_register_and_lookup():
        compendium = Compendium()
        compendium.register(alpha)
        compendium.register(beta)

        assert compendium.ritual("alpha") is alpha
        assert compendium.names() == ["alpha", "beta"]

    @staticmethod
    def test_two_rituals_of_one_name_collide_naming_both_sources():
        compendium = Compendium()
        compendium.register(alpha, source="rituals.first")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.register(same_name_as_alpha, source="rituals.second")

        assert "rituals.first" in str(raised.value)
        assert "rituals.second" in str(raised.value)

    # A submodule that reaches a sibling's ritual imports it, so the sweep of a
    # package hands the same object over once per module that names it.
    @staticmethod
    def test_the_same_ritual_reached_twice_registers_once():
        compendium = Compendium()
        compendium.register(alpha, source="rituals.first")
        compendium.register(alpha, source="rituals.second")

        assert compendium.names() == ["alpha"]

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

    # `measure` is a natural name in two rituals, and the loser used to vanish:
    # `rituals show` would then draw the other ritual's step under this one's
    # name, which is worse than refusing to draw anything.
    @staticmethod
    def test_two_steps_of_one_name_collide_naming_both_sources():
        compendium = Compendium()
        compendium.register_step(noop, source="rituals.first")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.register_step(same_name_as_noop, source="rituals.second")

        assert "rituals.first" in str(raised.value)
        assert "rituals.second" in str(raised.value)

    @staticmethod
    def test_the_same_step_reached_twice_registers_once():
        compendium = Compendium()
        compendium.register_step(noop, source="rituals.first")
        compendium.register_step(noop, source="rituals.second")

        assert compendium.step("noop") is noop
