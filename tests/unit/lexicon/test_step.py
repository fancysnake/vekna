import asyncio

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Done,
    RitualBoundaryError,
    RitualDefinitionError,
    StepBoundaryError,
    done,
    goto,
    step,
)


class Ping(BaseModel):
    n: int


class Pong(BaseModel):
    n: int


class Elsewhere(BaseModel):
    n: int


async def _emit(payload: Ping) -> object:
    await asyncio.sleep(0)
    return done(Pong(n=payload.n + 1))


class TestStepDecorator:
    @staticmethod
    def test_runs_body_and_returns_transition():
        wrapped = step(_emit)

        result = asyncio.run(wrapped.run(Ping(n=1)))

        assert isinstance(result, Done)
        assert result.result == Pong(n=2)

    @staticmethod
    def test_captures_payload_type_and_name():
        wrapped = step(_emit)

        assert wrapped.input_type is Ping
        assert wrapped.name == "_emit"

    @staticmethod
    def test_rejects_wrong_payload_type():
        wrapped = step(_emit)

        with pytest.raises(StepBoundaryError):
            asyncio.run(wrapped.run("not a ping"))

    @staticmethod
    def test_rejects_function_without_single_param():
        def _two(first: Ping, second: Ping) -> object:
            return done(Pong(n=first.n + second.n))

        with pytest.raises(RitualDefinitionError):
            step(_two)

    @staticmethod
    def test_rejects_unannotated_param():
        def _bare(value) -> object:
            return done(value)

        with pytest.raises(RitualDefinitionError):
            step(_bare)

    @staticmethod
    def test_rejects_a_payload_type_that_is_not_a_model():
        def _loose(payload: int) -> object:
            return done(Pong(n=payload))

        with pytest.raises(RitualDefinitionError, match="pydantic model"):
            step(_loose)


# A step two others transition into admits either shape.
class TestUnionPayload:
    @staticmethod
    async def _merge(payload: Ping | Pong) -> object:
        await asyncio.sleep(0)
        return done(Pong(n=payload.n))

    @classmethod
    def test_captures_the_union_as_its_input_type(cls):
        wrapped = step(cls._merge)

        assert wrapped.input_type == Ping | Pong

    @classmethod
    def test_admits_either_member(cls):
        wrapped = step(cls._merge)

        assert asyncio.run(wrapped.run(Ping(n=1))) == Done(result=Pong(n=1))
        assert asyncio.run(wrapped.run(Pong(n=2))) == Done(result=Pong(n=2))

    @classmethod
    def test_rejects_a_shape_outside_the_union(cls):
        wrapped = step(cls._merge)

        with pytest.raises(StepBoundaryError):
            asyncio.run(wrapped.run(Elsewhere(n=1)))

    @staticmethod
    def test_rejects_a_union_with_a_non_model_member():
        def _mixed(payload: Ping | int) -> object:
            return done(Pong(n=int(payload)))

        with pytest.raises(RitualDefinitionError, match="union"):
            step(_mixed)


class TestTransitionValues:
    @staticmethod
    def test_done_rejects_a_value_that_is_not_a_model():
        with pytest.raises(RitualBoundaryError, match="done takes a pydantic model"):
            done("green")

    @staticmethod
    def test_goto_rejects_a_payload_that_is_not_a_model():
        target = step(_emit)

        with pytest.raises(RitualBoundaryError, match="goto takes a pydantic model"):
            goto(target, 3)

    @staticmethod
    def test_nothing_is_a_transition_value():
        assert done().result is None
        assert goto(step(_emit)).payload is None
