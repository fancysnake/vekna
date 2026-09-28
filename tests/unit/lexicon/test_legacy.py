# ponytail: the pre-#103 `goto`/`done` path, kept for cabinet 0.3.0. Delete this
# file with the shim.
import asyncio
import io

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Done,
    Goto,
    NoComponents,
    RitualBoundaryError,
    Transition,
    done,
    goto,
    ritual,
    step,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast, step_taking
from vekna.lexicon._mills.graph import START, UNKNOWN, step_graph


class Work(BaseModel):
    left: int


class Landed(BaseModel):
    left: int


# Two legacy steps on one class, the way cabinet feeds one `Work` to fifteen.
@step
def hop(work: Work) -> Transition:
    if not work.left:
        return goto(land, Landed(left=0))
    return goto(hop, Work(left=work.left - 1))


@step
def skip(work: Work) -> Transition:
    return done(work)


# A new-style step a legacy one reaches by name.
@step
def land(landed: Landed) -> Done[Landed]:
    return Done(landed)


# The other legacy shape: an optional payload, reached by a bare `goto`.
@step
def nudge(work: Work | None) -> Transition:
    return done(work or Work(left=-1))


@ritual("hopping")
def hopping(_: NoComponents) -> Transition:
    return goto(hop, Work(left=2))


@ritual("nudging")
def nudging(_: NoComponents) -> Transition:
    return goto(nudge)


def _cast(the_ritual) -> BaseModel | None:
    return asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=NoComponents(),
            grimoire=Grimoire(cast_id="c1"),
            channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
        )
    )


class TestLegacyStep:
    @staticmethod
    def test_declares_no_exits_and_is_not_registered_by_class():
        assert hop.exits is None
        assert hop.ends is True
        assert step_taking(Work) is None

    @staticmethod
    def test_two_legacy_steps_may_share_a_payload_class():
        assert hop.payloads == skip.payloads == (Work,)

    @staticmethod
    def test_goto_names_its_target_and_the_engine_follows_it():
        assert _cast(hopping) == Landed(left=0)

    @staticmethod
    def test_a_bare_goto_reaches_a_step_whose_payload_is_optional():
        assert _cast(nudging) == Work(left=-1)

    @staticmethod
    def test_an_optional_payload_declares_the_model_alone():
        assert nudge.payloads == (Work,)

    @staticmethod
    def test_goto_rejects_a_payload_that_is_not_a_model():
        with pytest.raises(RitualBoundaryError, match="goto takes a pydantic model"):
            goto(hop, "not a model")

    @staticmethod
    def test_done_is_the_generic_done():
        assert done() == Done(None)
        assert done(Work(left=1)) == Done(Work(left=1))
        assert isinstance(goto(hop, Work(left=1)), Goto)

    @staticmethod
    def test_the_graph_draws_a_legacy_ritual_as_unknown():
        assert step_graph(hopping) == [(START, [UNKNOWN])]
