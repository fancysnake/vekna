import asyncio

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, RitualDefinitionError, StepBoundaryError, done, step


class Ping(BaseModel):
    n: int


class Pong(BaseModel):
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
