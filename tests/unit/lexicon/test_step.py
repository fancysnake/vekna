import asyncio
from collections.abc import Awaitable
from typing import Literal

import pytest
from pydantic import BaseModel

from vekna.lexicon import (
    Directory,
    Done,
    RitualBoundaryError,
    RitualDefinitionError,
    StepBoundaryError,
    ritual,
    step,
)
from vekna.lexicon._mills.dispatch import component_flags
from vekna.lexicon._mills.engine import step_taking


class Ping(BaseModel):
    n: int


class Pong(BaseModel):
    n: int


class Elsewhere(BaseModel):
    n: int


# Deliberately `async def`: it is what keeps the wrapper's awaiting path under
# test, against `TestSyncBody` covering the other one.
async def _emit(payload: Ping) -> Done[Pong]:
    await asyncio.sleep(0)
    return Done(Pong(n=payload.n + 1))


class TestStepDecorator:
    @staticmethod
    def test_runs_body_and_returns_transition():
        wrapped = step(_emit)

        result = asyncio.run(wrapped.run(Ping(n=1)))

        assert result == Done(Pong(n=2))

    @staticmethod
    def test_captures_payload_exits_and_name():
        def _hop(payload: Ping) -> Pong | Elsewhere | Done[None]:
            return Done(None) if payload.n else Pong(n=1)

        wrapped = step(_hop)

        assert wrapped.name == "_hop"
        assert wrapped.payloads == (Ping,)
        assert wrapped.exits == (Pong, Elsewhere)
        assert wrapped.ends is True

    @staticmethod
    def test_a_step_that_never_finishes_does_not_end():
        def _forward(payload: Ping) -> Pong:
            return Pong(n=payload.n)

        wrapped = step(_forward)

        assert wrapped.exits == (Pong,)
        assert wrapped.ends is False

    @staticmethod
    def test_rejects_wrong_payload_type():
        wrapped = step(_emit)

        with pytest.raises(StepBoundaryError, match="expected Ping, got str"):
            asyncio.run(wrapped.run("not a ping"))

    @staticmethod
    def test_rejects_an_absent_payload():
        wrapped = step(_emit)

        with pytest.raises(StepBoundaryError, match="expected Ping, got NoneType"):
            asyncio.run(wrapped.run(None))

    @staticmethod
    def test_rejects_function_without_single_param():
        def _two(first: Ping, second: Ping) -> Done[Pong]:
            return Done(Pong(n=first.n + second.n))

        with pytest.raises(RitualDefinitionError):
            step(_two)

    @staticmethod
    def test_rejects_unannotated_param():
        def _bare(value) -> Done[Pong]:
            return Done(value)

        with pytest.raises(RitualDefinitionError):
            step(_bare)

    @staticmethod
    def test_rejects_a_payload_type_that_is_not_a_model():
        def _loose(payload: int) -> Done[Pong]:
            return Done(Pong(n=payload))

        with pytest.raises(RitualDefinitionError, match="pydantic model"):
            step(_loose)

    # The return annotation is the graph, so a body without one has no edges
    # to draw and nothing for mypy to hold it to.
    @staticmethod
    def test_rejects_a_step_without_a_return_annotation():
        def _mute(payload: Ping):
            return Done(Pong(n=payload.n))

        with pytest.raises(RitualDefinitionError, match="declare its exits"):
            step(_mute)

    @staticmethod
    def test_rejects_an_exit_that_is_not_a_model_naming_it():
        def _stray(payload: Ping) -> int | Done[Pong]:
            return payload.n

        with pytest.raises(RitualDefinitionError, match=r"Done\[\.\.\.\], not int"):
            step(_stray)

    # What a migrating author writes first, and the anonymous message read as
    # though the annotation had been ignored.
    @staticmethod
    def test_rejects_a_bare_done_and_says_to_name_what_it_carries():
        def _vague(payload: Ping) -> Done:
            return Done(Pong(n=payload.n))

        with pytest.raises(RitualDefinitionError, match="bare Done: name what it"):
            step(_vague)

    # The erased `BaseModel` is an exit like any other, and `check_exits` is
    # what refuses it.
    @staticmethod
    def test_an_erased_basemodel_exit_is_an_exit_like_any_other():
        class Fresh(BaseModel):
            pass

        def _erased(payload: Fresh) -> BaseModel | Done[Pong]:
            return Done(Pong(n=len(repr(payload))))

        wrapped = step(_erased)

        assert wrapped.exits == (BaseModel,)
        assert step_taking(Fresh) is wrapped


# A step two others transition into admits either shape.
class TestUnionPayload:
    @staticmethod
    def _merge(payload: Ping | Pong) -> Done[Pong]:
        return Done(Pong(n=payload.n))

    @classmethod
    def test_captures_every_member_as_a_payload(cls):
        wrapped = step(cls._merge)

        assert wrapped.payloads == (Ping, Pong)

    @classmethod
    def test_admits_either_member(cls):
        wrapped = step(cls._merge)

        assert asyncio.run(wrapped.run(Ping(n=1))) == Done(Pong(n=1))
        assert asyncio.run(wrapped.run(Pong(n=2))) == Done(Pong(n=2))

    @classmethod
    def test_rejects_a_shape_outside_the_union(cls):
        wrapped = step(cls._merge)

        with pytest.raises(StepBoundaryError, match=r"expected Ping \| Pong"):
            asyncio.run(wrapped.run(Elsewhere(n=1)))

    @staticmethod
    def test_rejects_a_union_with_a_non_model_member():
        def _mixed(payload: Ping | int) -> Done[Pong]:
            return Done(Pong(n=int(payload)))

        with pytest.raises(RitualDefinitionError, match="union"):
            step(_mixed)


# A body with nothing to await is written `def`, and the wrapper awaits only
# what arrives needing it.
class TestSyncBody:
    @staticmethod
    def test_runs_a_step_that_only_routes():
        def _route(payload: Ping) -> Done[Pong]:
            return Done(Pong(n=payload.n))

        wrapped = step(_route)

        assert asyncio.run(wrapped.run(Ping(n=3))) == Done(Pong(n=3))

    @staticmethod
    def test_still_checks_the_payload_of_a_step_that_only_routes():
        def _route(payload: Ping) -> Done[Pong]:
            return Done(Pong(n=payload.n))

        wrapped = step(_route)

        with pytest.raises(StepBoundaryError):
            asyncio.run(wrapped.run(Elsewhere(n=1)))

    @staticmethod
    def test_runs_an_entrypoint_that_only_names_the_first_step():
        @ritual("plain")
        def _enter(components: Ping) -> Ping:
            return components

        assert asyncio.run(_enter.run(Ping(n=4))) == Ping(n=4)
        assert (_enter.exits, _enter.ends) == ((Ping,), False)

    @staticmethod
    def test_still_checks_the_components_of_an_entrypoint_that_only_routes():
        @ritual("plain")
        def _enter(components: Ping) -> Done[Pong]:
            return Done(Pong(n=components.n))

        with pytest.raises(RitualBoundaryError):
            asyncio.run(_enter.run(Elsewhere(n=1)))

    # Not a designed feature — a consequence of asking the value whether it
    # needs awaiting rather than asking the function whether it was `async`.
    # Pinned because it is the forgiving direction: an author who writes
    # `return _helper(p)` and forgets the `await` gets working code, and anyone
    # switching the wrapper to `iscoroutinefunction` would take that away.
    @staticmethod
    def test_awaits_a_coroutine_a_sync_body_hands_back():
        async def _later(payload: Ping) -> Done[Pong]:
            await asyncio.sleep(0)
            return Done(Pong(n=payload.n))

        def _defers(payload: Ping) -> Awaitable[Done[Pong]]:
            return _later(payload)

        wrapped = step(_defers)

        assert asyncio.run(wrapped.run(Ping(n=5))) == Done(Pong(n=5))
        assert wrapped.ends is True


class TestDone:
    @staticmethod
    def test_rejects_a_value_that_is_not_a_model():
        with pytest.raises(RitualBoundaryError, match="Done takes a pydantic model"):
            Done("green")

    @staticmethod
    def test_nothing_is_a_result():
        assert Done(None).result is None


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
