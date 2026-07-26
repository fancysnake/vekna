import asyncio
from typing import Literal

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Directory,
    Done,
    RitualBoundaryError,
    RitualDefinitionError,
    StepBoundaryError,
    done,
    goto,
    step,
)
from vekna.lexicon._mills.dispatch import _type_name, component_flags


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


class TestComponentFlags:
    @staticmethod
    def test_names_a_plain_type():
        class Plain(BaseModel):
            count: int

        assert component_flags(Plain) == [("count", "int", True)]

    @staticmethod
    def test_drops_the_none_arm_of_an_optional_component():
        class Note(BaseModel):
            note: str | None = None

        assert component_flags(Note) == [("note", "str", False)]

    @staticmethod
    def test_joins_the_members_of_a_union():
        class Either(BaseModel):
            value: int | str

        assert component_flags(Either) == [("value", "int|str", True)]

    @staticmethod
    def test_names_an_annotated_component_by_the_type_it_validates():
        class Where(BaseModel):
            root: Directory | None = None

        assert component_flags(Where) == [("root", "Path", False)]

    @staticmethod
    def test_names_a_generic_alias_by_its_origin():
        class Tags(BaseModel):
            tags: list[str] = []

        assert component_flags(Tags) == [("tags", "list", False)]

    @staticmethod
    def test_names_a_literal_by_its_construct():
        class Mode(BaseModel):
            mode: Literal["fast", "slow"] = "fast"

        assert component_flags(Mode) == [("mode", "Literal", False)]

    @staticmethod
    def test_falls_back_when_an_annotation_is_not_a_type_at_all():
        assert _type_name(object()) == "value"
