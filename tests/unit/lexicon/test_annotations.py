import functools

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, RitualDefinitionError, ritual, step


class Ping(BaseModel):
    n: int


class Pong(BaseModel):
    n: int


class TestRitualSignature:
    @staticmethod
    def test_the_ritual_carries_the_name_given_not_the_function_name():
        @ritual("echo")
        def _echo(components: Ping) -> Done[Ping]:
            return Done(components)

        assert _echo.name == "echo"

    @staticmethod
    def test_a_second_parameter_is_refused_naming_the_components():
        with pytest.raises(
            RitualDefinitionError,
            match=r"^@ritual 'pair' must take exactly one components parameter$",
        ):

            @ritual("pair")
            def pair(components: Ping, extra: Pong) -> Done[Ping]:
                return Done(Ping(n=components.n + extra.n))


class TestStepSignature:
    @staticmethod
    def test_a_second_parameter_is_refused_naming_the_payload():
        def _pair(payload: Ping, extra: Pong) -> Done[Pong]:
            return Done(Pong(n=payload.n + extra.n))

        with pytest.raises(
            RitualDefinitionError,
            match=r"^@step '_pair' must take exactly one payload parameter$",
        ):
            step(_pair)

    @staticmethod
    def test_a_payload_that_is_no_model_is_refused_saying_what_is_legal():
        def _loose(payload: int) -> Done[Pong]:
            return Done(Pong(n=payload))

        with pytest.raises(
            RitualDefinitionError,
            match=(
                r"^@step '_loose' needs a pydantic model, or a union of them, "
                r"as its payload type$"
            ),
        ):
            step(_loose)


class TestStepExits:
    @staticmethod
    def test_a_bare_done_is_refused_saying_how_to_name_no_result():
        def _vague(payload: Ping) -> Done:
            return Done(Pong(n=payload.n))

        with pytest.raises(
            RitualDefinitionError,
            match=(
                r"^@step '_vague' returns a bare Done: name what it carries — "
                r"Done\[None\] for a body that ends with no result$"
            ),
        ):
            step(_vague)

    # No annotation, no member: the message stops where the naming would go.
    @staticmethod
    def test_a_missing_return_annotation_names_no_member():
        def _mute(payload: Ping):
            return Done(Pong(n=payload.n))

        with pytest.raises(
            RitualDefinitionError,
            match=(
                r"^@step '_mute' must declare its exits: a return annotation "
                r"naming step payloads and Done\[\.\.\.\]$"
            ),
        ):
            step(_mute)

    # A callable instance passes `get_type_hints` yet has no `__name__`.
    @staticmethod
    def test_an_exit_with_no_name_is_called_a_value():
        def _odd(payload: Ping) -> int:
            return payload.n

        _odd.__annotations__["return"] = functools.partial(int)

        with pytest.raises(RitualDefinitionError, match=r", not value$"):
            step(_odd)
