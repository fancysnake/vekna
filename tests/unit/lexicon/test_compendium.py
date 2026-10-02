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
        compendium.register(same_name_as_alpha, origin="rituals.second")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.check()

        assert str(raised.value) == (
            "ritual 'alpha' is already registered"
            " — declared in both rituals.first and rituals.second"
        )

    # A source is what a collision names, not what makes it one.
    @staticmethod
    def test_two_rituals_of_one_name_collide_without_a_source():
        compendium = Compendium()
        compendium.register(alpha)
        compendium.register(same_name_as_alpha)

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.check()

        assert "'alpha' is already registered" in str(raised.value)

    @staticmethod
    def test_every_collision_is_reported_at_once():
        compendium = Compendium()
        compendium.register(alpha, origin="local")
        compendium.register(beta, origin="local")
        compendium.register(same_name_as_alpha, origin="other")
        compendium.register(replace(beta, name="beta"), origin="other")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.check()

        assert str(raised.value) == (
            "2 name collisions:\n"
            "  ritual 'alpha' — declared in both local and other\n"
            "  ritual 'beta' — declared in both local and other"
        )

    @staticmethod
    def test_no_collision_checks_clean():
        compendium = Compendium()
        compendium.register(alpha)

        compendium.check()

        assert compendium.names() == ["alpha"]

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


class TestNamespaces:
    @staticmethod
    def test_one_name_in_two_namespaces_does_not_collide():
        compendium = Compendium()
        compendium.register(alpha)
        compendium.register(same_name_as_alpha, namespace="tome")

        compendium.check()

        assert compendium.names() == ["alpha", "tome:alpha"]

    @staticmethod
    def test_a_qualified_name_resolves_and_carries_its_namespace():
        compendium = Compendium()
        compendium.register(alpha)
        compendium.register(same_name_as_alpha, namespace="tome")

        found = compendium.ritual("tome:alpha")

        assert found.name == "tome:alpha"
        assert found.run is same_name_as_alpha.run

    @staticmethod
    def test_a_bare_name_prefers_the_projects_own():
        compendium = Compendium()
        compendium.register(same_name_as_alpha, namespace="tome")
        compendium.register(alpha)

        assert compendium.ritual("alpha") is alpha

    @staticmethod
    def test_a_bare_name_offered_by_one_tome_resolves_to_it():
        compendium = Compendium()
        compendium.register(beta)
        compendium.register(alpha, namespace="tome")

        assert compendium.ritual("alpha").name == "tome:alpha"

    @staticmethod
    def test_a_bare_name_offered_by_two_tomes_names_both():
        compendium = Compendium()
        compendium.register(alpha, namespace="acme")
        compendium.register(same_name_as_alpha, namespace="cabinet")

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.ritual("alpha")

        assert str(raised.value) == (
            "ritual 'alpha' is ambiguous: acme:alpha, cabinet:alpha"
        )

    @staticmethod
    def test_a_collision_within_a_tome_is_named_qualified():
        compendium = Compendium()
        compendium.register(alpha, namespace="tome", origin="tome.a")
        compendium.register(same_name_as_alpha, namespace="tome", origin="tome.b")

        with pytest.raises(RitualDefinitionError, match="'tome:alpha'"):
            compendium.check()

    @staticmethod
    def test_the_projects_own_list_first_then_each_tome():
        compendium = Compendium()
        compendium.register(alpha, namespace="zeta")
        compendium.register(beta, namespace="acme")
        compendium.register(same_name_as_alpha)

        assert compendium.names() == ["alpha", "acme:beta", "zeta:alpha"]


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

    # The rejected step is registered nowhere: `vekna --help` swallows the
    # error and carries on, so a half-filled table would outlive it.
    @staticmethod
    def test_a_collision_on_a_second_payload_registers_neither():
        class Fresh(BaseModel):
            pass

        with pytest.raises(RitualDefinitionError, match="'noop'"):

            @step
            def both(_: Fresh | State) -> Done[None]:
                return Done(None)

        assert step_taking(Fresh) is None

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
