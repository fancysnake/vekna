import asyncio
from functools import partial

from pydantic import BaseModel

from vekna.lexicon import NoComponents, Transition, done, goto, ritual, step
from vekna.lexicon._mills.dispatch import source_text
from vekna.lexicon._mills.engine import Compendium
from vekna.lexicon._mills.graph import ENDS, START, step_graph
from vekna.lexicon._pacts import Ritual, Step


class State(BaseModel):
    x: int


@step
def finish(state: State) -> Transition:
    return done(state)


@step
def tick(state: State) -> Transition:
    if not state.x:
        return done(state)
    return goto(finish, State(x=state.x - 1))


@step
def branchy(state: State) -> Transition:
    if state.x:
        return goto(finish, state)
    return goto(finish, State(x=1))


@step
def spin(state: State) -> Transition:
    return goto(spin, state)


@ritual("countdown")
def countdown(components: State) -> Transition:
    return goto(tick, State(x=components.x))


@ritual("spinner")
def spinner(_: NoComponents) -> Transition:
    return goto(spin, State(x=0))


# Stands in for a hand-built `Ritual.run`, which is typed Awaitable whichever
# way the body that produced it was written.
async def _never(_: BaseModel) -> Transition:
    await asyncio.sleep(0)
    return done()


def _hand_built_ritual(source: str | None) -> Ritual:
    return Ritual(
        name="handmade", components=NoComponents, run=_never, max_steps=1, source=source
    )


# A step whose body holds a string starting at column zero keeps its own
# indentation after dedent, so its source cannot be parsed on its own.
def _unindentable_step() -> Step:
    @step
    def odd(state: State) -> Transition:
        note = """
text at column zero
"""
        return done(note + str(state.x))

    return odd


class TestStepGraph:
    @staticmethod
    def test_walks_from_the_ritual_through_every_named_step():
        compendium = Compendium()
        compendium.register(countdown)
        compendium.register_step(tick)
        compendium.register_step(finish)

        graph = step_graph(compendium, countdown)

        assert graph == [
            (START, ["tick"]),
            ("tick", ["finish", ENDS]),
            ("finish", [ENDS]),
        ]

    @staticmethod
    def test_target_named_twice_is_listed_once():
        compendium = Compendium()
        compendium.register_step(branchy)
        compendium.register_step(finish)
        the_ritual = _hand_built_ritual(
            "async def handmade():\n    return goto(branchy)\n"
        )

        assert step_graph(compendium, the_ritual) == [
            (START, ["branchy"]),
            ("branchy", ["finish"]),
            ("finish", [ENDS]),
        ]

    @staticmethod
    def test_step_the_compendium_never_saw_is_a_leaf():
        compendium = Compendium()
        compendium.register(countdown)

        assert step_graph(compendium, countdown) == [(START, ["tick"])]

    @staticmethod
    def test_self_referencing_step_is_walked_once():
        compendium = Compendium()
        compendium.register(spinner)
        compendium.register_step(spin)

        assert step_graph(compendium, spinner) == [
            (START, ["spin"]),
            ("spin", ["spin"]),
        ]

    @staticmethod
    def test_ritual_without_source_has_no_targets():
        the_ritual = _hand_built_ritual(None)

        assert step_graph(Compendium(), the_ritual) == [(START, [])]

    @staticmethod
    def test_source_that_does_not_parse_has_no_targets():
        the_ritual = _hand_built_ritual("async def handmade(:\n")

        assert step_graph(Compendium(), the_ritual) == [(START, [])]

    @staticmethod
    def test_step_whose_source_does_not_parse_is_a_leaf():
        odd = _unindentable_step()
        compendium = Compendium()
        compendium.register_step(odd)
        the_ritual = _hand_built_ritual("async def handmade():\n    return goto(odd)\n")

        assert step_graph(compendium, the_ritual) == [(START, ["odd"]), ("odd", [])]


class TestSourceText:
    @staticmethod
    def test_reads_the_source_of_a_function():
        text = source_text(_never)

        assert text is not None
        assert text.startswith("async def _never")

    @staticmethod
    def test_returns_none_when_there_is_no_source_to_read():
        assert source_text(partial(_never)) is None
