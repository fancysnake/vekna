import asyncio
from dataclasses import replace

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, RitualDefinitionError, StepBoundaryError, ritual, step
from vekna.lexicon._mills.engine import Compendium, register_step, step_for, step_taking
from vekna.lexicon._pacts import Ritual, RitualSource


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


@ritual("alpha")
async def third_alpha(components: State) -> Done[State]:
    await asyncio.sleep(0)
    return Done(State(x=components.x))


@ritual("beta")
async def same_name_as_beta(components: State) -> Done[State]:
    await asyncio.sleep(0)
    return Done(State(x=components.x))


def _shelf(
    *rituals: Ritual, namespace: str = "", origin: str = "rituals"
) -> tuple[str, RitualSource]:
    return namespace, RitualSource(origin=origin, rituals=list(rituals))


class TestCompendium:
    @staticmethod
    def test_lookup():
        compendium = Compendium([_shelf(alpha, beta)])

        assert compendium.ritual("alpha") is alpha
        assert compendium.names() == ["alpha", "beta"]

    @staticmethod
    def test_two_rituals_of_one_name_collide_naming_both_sources():
        shelves = [
            _shelf(alpha, origin="rituals.first"),
            _shelf(same_name_as_alpha, origin="rituals.second"),
        ]

        with pytest.raises(RitualDefinitionError) as raised:
            Compendium(shelves)

        assert str(raised.value) == (
            "name collisions:\n"
            "  ritual 'alpha' — declared in both rituals.first and rituals.second"
        )

    @staticmethod
    def test_every_collision_is_reported_at_once():
        shelves = [
            _shelf(alpha, beta, origin="local"),
            _shelf(same_name_as_alpha, same_name_as_beta, origin="other"),
        ]

        with pytest.raises(RitualDefinitionError) as raised:
            Compendium(shelves)

        assert str(raised.value) == (
            "name collisions:\n"
            "  ritual 'alpha' — declared in both local and other\n"
            "  ritual 'beta' — declared in both local and other"
        )

    @staticmethod
    def test_a_rival_reached_twice_is_one_collision():
        shelves = [
            _shelf(alpha, origin="local"),
            _shelf(same_name_as_alpha, origin="other.a"),
            _shelf(same_name_as_alpha, origin="other.b"),
        ]

        with pytest.raises(RitualDefinitionError) as raised:
            Compendium(shelves)

        assert str(raised.value) == (
            "name collisions:\n  ritual 'alpha' — declared in both local and other.a"
        )

    @staticmethod
    def test_two_rivals_to_one_ritual_are_two_collisions():
        shelves = [
            _shelf(alpha, origin="local"),
            _shelf(same_name_as_alpha, origin="other.a"),
            _shelf(third_alpha, origin="other.b"),
        ]

        with pytest.raises(RitualDefinitionError) as raised:
            Compendium(shelves)

        assert str(raised.value) == (
            "name collisions:\n"
            "  ritual 'alpha' — declared in both local and other.a\n"
            "  ritual 'alpha' — declared in both local and other.b"
        )

    # A submodule that reaches a sibling's ritual imports it, so the sweep of a
    # package hands the same object over once per module that names it.
    @staticmethod
    def test_the_same_ritual_reached_twice_registers_once():
        compendium = Compendium(
            [
                _shelf(alpha, origin="rituals.first"),
                _shelf(alpha, origin="rituals.second"),
            ]
        )

        assert compendium.names() == ["alpha"]

    @staticmethod
    def test_a_copy_of_one_ritual_is_the_same_ritual():
        compendium = Compendium([_shelf(alpha), _shelf(replace(alpha, max_steps=1))])

        assert compendium.ritual("alpha") is alpha

    @staticmethod
    def test_a_missing_ritual_lists_the_known_ones():
        compendium = Compendium([_shelf(alpha, beta)])

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.ritual("nope")

        assert str(raised.value) == (
            "no ritual named 'nope' — known rituals: alpha, beta"
        )

    @staticmethod
    def test_a_missing_ritual_in_an_empty_library_lists_nothing():
        compendium = Compendium([])

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.ritual("nope")

        assert str(raised.value) == "no ritual named 'nope'"


class TestNamespaces:
    @staticmethod
    def test_one_name_in_two_namespaces_does_not_collide():
        compendium = Compendium(
            [_shelf(alpha), _shelf(same_name_as_alpha, namespace="tome")]
        )

        assert compendium.names() == ["alpha", "tome:alpha"]

    @staticmethod
    def test_a_qualified_name_resolves_and_carries_its_namespace():
        compendium = Compendium(
            [_shelf(alpha), _shelf(same_name_as_alpha, namespace="tome")]
        )

        found = compendium.ritual("tome:alpha")

        assert found.name == "tome:alpha"
        assert found.run is same_name_as_alpha.run

    @staticmethod
    def test_a_bare_name_prefers_the_projects_own():
        compendium = Compendium(
            [_shelf(same_name_as_alpha, namespace="tome"), _shelf(alpha)]
        )

        assert compendium.ritual("alpha") is alpha

    @staticmethod
    def test_a_bare_name_offered_by_one_tome_resolves_to_it():
        compendium = Compendium(
            [
                _shelf(beta),
                _shelf(alpha, namespace="tome"),
                _shelf(same_name_as_beta, namespace="other"),
            ]
        )

        assert compendium.ritual("alpha").name == "tome:alpha"

    @staticmethod
    def test_a_bare_name_offered_by_two_tomes_names_both():
        compendium = Compendium(
            [
                _shelf(alpha, namespace="acme"),
                _shelf(same_name_as_alpha, namespace="cabinet"),
            ]
        )

        with pytest.raises(RitualDefinitionError) as raised:
            compendium.ritual("alpha")

        assert str(raised.value) == (
            "ritual 'alpha' is ambiguous: acme:alpha, cabinet:alpha"
        )

    @staticmethod
    def test_a_collision_within_a_tome_is_named_qualified():
        shelves = [
            _shelf(alpha, namespace="tome", origin="tome.a"),
            _shelf(same_name_as_alpha, namespace="tome", origin="tome.b"),
        ]

        with pytest.raises(RitualDefinitionError, match="'tome:alpha'"):
            Compendium(shelves)

    @staticmethod
    def test_the_projects_own_list_first_then_each_tome():
        compendium = Compendium(
            [
                _shelf(alpha, namespace="zeta"),
                _shelf(beta, namespace="acme"),
                _shelf(same_name_as_alpha),
            ]
        )

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
    def test_a_class_holding_something_else_where_a_step_lives_is_none():
        class Squatter(BaseModel):
            __vekna_step__ = "not a step"

        assert step_taking(Squatter) is None

    @staticmethod
    def test_a_subclass_of_a_taken_class_is_taken_by_no_step():
        class Derived(State):
            pass

        assert step_taking(Derived) is None

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

        here = noop.source
        assert str(raised.value) == (
            f"State is the payload of both step 'noop' ({here}) and step 'again'"
            f" ({here}) — one payload class, one step"
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
        with pytest.raises(
            RitualDefinitionError, match=r"'noop' \(.*\) and step 'copy'"
        ):
            register_step(replace(noop, name="copy"))
