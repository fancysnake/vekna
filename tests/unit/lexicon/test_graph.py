import asyncio

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Done,
    Failure,
    NoComponents,
    RitualDefinitionError,
    ritual,
    step,
)
from vekna.lexicon._mills.graph import ENDS, ON_FAILURE, START, step_graph
from vekna.lexicon._pacts import Ritual, Step, Transition


class Tick(BaseModel):
    x: int


class Fin(BaseModel):
    x: int


class Ripe(BaseModel):
    pass


class Rotten(BaseModel):
    pass


class Sort(BaseModel):
    ripe: bool


class Spin(BaseModel):
    pass


@step
def finish(state: Fin) -> Done[Fin]:
    return Done(state)


@step
def tick(state: Tick) -> Fin | Done[Tick]:
    if not state.x:
        return Done(state)
    return Fin(x=state.x - 1)


@step
def eat(_: Ripe | Rotten) -> Done[None]:
    return Done(None)


@step
def sort(state: Sort) -> Ripe | Rotten:
    return Ripe() if state.ripe else Rotten()


@step
def spin(state: Spin) -> Spin:
    return state


@ritual("countdown")
def countdown(components: Tick) -> Tick:
    return Tick(x=components.x)


@ritual("sorter")
def sorter(_: NoComponents) -> Sort:
    return Sort(ripe=True)


@ritual("spinner")
def spinner(_: NoComponents) -> Spin:
    return Spin()


# Stands in for a hand-built `Ritual.run`, which is typed Awaitable whichever
# way the body that produced it was written.
async def _never(_: BaseModel) -> Transition:
    await asyncio.sleep(0)
    return Done(None)


def _hand_built_ritual(
    *, exits: tuple[type[BaseModel], ...], ends: bool = False
) -> Ritual:
    return Ritual(
        name="handmade",
        components=NoComponents,
        run=_never,
        max_steps=1,
        exits=exits,
        ends=ends,
    )


class TestStepGraph:
    @staticmethod
    def test_walks_from_the_ritual_through_every_exit():
        assert step_graph(countdown) == [
            (START, ["tick"]),
            ("tick", ["finish", ENDS]),
            ("finish", [ENDS]),
        ]

    # Two payload classes, one step taking both: one edge, not two.
    @staticmethod
    def test_a_union_exit_names_its_step_once():
        assert step_graph(sorter) == [
            (START, ["sort"]),
            ("sort", ["eat"]),
            ("eat", [ENDS]),
        ]

    @staticmethod
    def test_self_referencing_step_is_walked_once():
        assert step_graph(spinner) == [(START, ["spin"]), ("spin", ["spin"])]

    @staticmethod
    def test_ritual_that_only_ends_has_one_edge():
        assert step_graph(_hand_built_ritual(exits=(), ends=True)) == [(START, [ENDS])]

    # The one mis-wire mypy cannot see: the annotation is well-typed, it just
    # names a class nothing was decorated with.
    @staticmethod
    def test_an_exit_no_step_takes_is_refused_naming_both():
        class Stray(BaseModel):
            pass

        with pytest.raises(
            RitualDefinitionError, match=r"\(start\) may return Stray, which no step"
        ):
            step_graph(_hand_built_ritual(exits=(Stray,)))

    # A step's name routes nothing, so two of one name are legal — and the
    # second one's exits are checked like any other.
    @staticmethod
    def test_two_steps_of_one_name_are_both_walked():
        class Left(BaseModel):
            pass

        class Right(BaseModel):
            pass

        class Astray(BaseModel):
            pass

        def _ends() -> Step:
            @step
            def measure(_: Left) -> Done[None]:
                return Done(None)

            return measure

        def _strays() -> Step:
            @step
            def measure(_: Right) -> Astray:
                return Astray()

            return measure

        _ends()
        _strays()

        with pytest.raises(RitualDefinitionError, match="measure may return Astray"):
            step_graph(_hand_built_ritual(exits=(Left, Right)))

    # A library holds many rituals, and `(start)` names none of them.
    @staticmethod
    def test_an_unwired_exit_on_a_ritual_names_the_ritual():
        class Stray(BaseModel):
            pass

        with pytest.raises(RitualDefinitionError, match="ritual 'handmade'"):
            step_graph(_hand_built_ritual(exits=(Stray,)))

    @staticmethod
    def test_an_unwired_exit_deeper_in_names_the_step():
        class Stray(BaseModel):
            pass

        class Lead(BaseModel):
            pass

        @step
        def lead(_: Lead) -> Stray:
            return Stray()

        with pytest.raises(RitualDefinitionError, match="lead may return Stray"):
            step_graph(_hand_built_ritual(exits=(Lead,)))

    # Dedupe is by Step, not by name: two distinct steps sharing a name are
    # two edges out of the row, as they are two rows further down.
    @staticmethod
    def test_two_steps_of_one_name_are_two_edges():
        class Left(BaseModel):
            pass

        class Right(BaseModel):
            pass

        def _taking_left() -> Step:
            @step
            def measure(_: Left) -> Done[None]:
                return Done(None)

            return measure

        def _taking_right() -> Step:
            @step
            def measure(_: Right) -> Done[None]:
                return Done(None)

            return measure

        _taking_left()
        _taking_right()

        assert step_graph(_hand_built_ritual(exits=(Left, Right))) == [
            (START, ["measure", "measure"]),
            ("measure", [ENDS]),
            ("measure", [ENDS]),
        ]

    # `triage` is named by no exit: the raise in `attempt` is its only way in,
    # and a recovery path missing from the graph is one nobody reviews.
    @staticmethod
    def test_a_failure_edge_is_drawn_and_its_step_walked():
        class Attempt(BaseModel):
            pass

        @step
        def attempt(_: Attempt) -> Done[None]:
            return Done(None)

        @step
        def triage(_: Failure[Attempt]) -> Attempt | Done[None]:
            return Done(None)

        assert step_graph(_hand_built_ritual(exits=(Attempt,))) == [
            (START, ["attempt"]),
            ("attempt", [ENDS, f"triage{ON_FAILURE}"]),
            ("triage", ["attempt", ENDS]),
        ]
