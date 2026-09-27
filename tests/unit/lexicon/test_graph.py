import asyncio

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, NoComponents, RitualDefinitionError, ritual, step
from vekna.lexicon._mills.graph import ENDS, START, step_graph
from vekna.lexicon._pacts import Ritual, Transition


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
