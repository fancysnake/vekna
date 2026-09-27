import asyncio
from dataclasses import replace

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, RitualDefinitionError, StepBoundaryError, ritual, step
from vekna.lexicon._mills.engine import (
    Compendium,
    register_step,
    step_for,
    step_taking,
    steps_scope,
)


class State(BaseModel):
    x: int


class Other(BaseModel):
    x: int


class Third(BaseModel):
    x: int


@step
def noop(state: State) -> Done[State]:
    return Done(state)


@step
def either(state: Other | Third) -> Done[State]:
    return Done(State(x=state.x))


@ritual("alpha")
def alpha(components: State) -> State:
    return State(x=components.x)


@ritual("beta")
def beta(components: State) -> State:
    return State(x=components.x)


@ritual("alpha")
async def same_name_as_alpha(components: State) -> Done[State]:
    await asyncio.sleep(0)
    return Done(State(x=components.x))


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
        compendium.register(alpha, origin="rituals.first")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.register(same_name_as_alpha, origin="rituals.second")

        assert "rituals.first" in str(raised.value)
        assert "rituals.second" in str(raised.value)

    # A source is what a collision names, not what makes it one.
    @staticmethod
    def test_two_rituals_of_one_name_collide_without_a_source():
        compendium = Compendium()
        compendium.register(alpha)

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.register(same_name_as_alpha)

        assert "'alpha' is already registered" in str(raised.value)

    # A submodule that reaches a sibling's ritual imports it, so the sweep of a
    # package hands the same object over once per module that names it.
    @staticmethod
    def test_the_same_ritual_reached_twice_registers_once():
        compendium = Compendium()
        compendium.register(alpha, origin="rituals.first")
        compendium.register(alpha, origin="rituals.second")

        assert compendium.names() == ["alpha"]

    @staticmethod
    def test_missing_ritual_raises():
        compendium = Compendium()

        with pytest.raises(RitualDefinitionError):
            compendium.ritual("nope")


# A payload class is a step's identity, so the table is keyed by class and a
# name says nothing — `measure` in two rituals is two steps, and fine.
class TestStepTable:
    @staticmethod
    def test_a_decorated_step_is_found_by_its_payload_class():
        assert step_taking(State) is noop
        assert step_for(State(x=1)) is noop

    @staticmethod
    def test_a_union_payload_registers_every_member():
        assert step_taking(Other) is either
        assert step_taking(Third) is either

    @staticmethod
    def test_a_class_no_step_takes_is_none():
        class Stray(BaseModel):
            pass

        assert step_taking(Stray) is None

    @staticmethod
    def test_a_payload_no_step_takes_is_a_boundary_error():
        class Stray(BaseModel):
            pass

        with pytest.raises(StepBoundaryError, match="no step takes Stray"):
            step_for(Stray())

    @staticmethod
    def test_two_steps_taking_one_class_collide_naming_both():
        with pytest.raises(RitualDefinitionError) as raised:

            @step
            def again(state: State) -> Done[State]:
                return Done(state)

        assert "State is the payload of both step 'noop' and step 'again'" in str(
            raised.value
        )

    @staticmethod
    def test_a_member_of_a_union_already_taken_collides():
        with pytest.raises(RitualDefinitionError, match="'either'"):

            @step
            def again(state: Third) -> Done[State]:
                return Done(State(x=state.x))

    @staticmethod
    def test_the_same_step_registered_twice_is_one_step():
        register_step(noop)

        assert step_taking(State) is noop

    @staticmethod
    def test_a_renamed_copy_is_another_step():
        with pytest.raises(RitualDefinitionError, match="'noop' and step 'copy'"):
            register_step(replace(noop, name="copy"))


class TestStepsScope:
    @staticmethod
    def test_a_step_declared_inside_is_forgotten_at_the_end():
        class Passing(BaseModel):
            pass

        with steps_scope():

            @step
            def fleeting(_: Passing) -> Done[None]:
                return Done(None)

            inside = step_taking(Passing)

        assert inside is fleeting
        assert step_taking(Passing) is None

    @staticmethod
    def test_a_step_declared_before_is_kept():
        with steps_scope():
            pass

        assert step_taking(State) is noop

    @staticmethod
    def test_a_block_that_raises_still_forgets():
        class Passing(BaseModel):
            pass

        def declare_and_fail() -> None:
            @step
            def fleeting(_: Passing) -> Done[None]:
                return Done(None)

            raise RuntimeError(fleeting.name)

        with pytest.raises(RuntimeError), steps_scope():
            declare_and_fail()

        assert step_taking(Passing) is None
