import asyncio
from pathlib import Path
from typing import Self

import pytest
from pydantic import BaseModel, Field, model_validator

from vekna.lexicon import Done, RitualDefinitionError
from vekna.lexicon._mills.defaults import Default, Defaults
from vekna.lexicon._pacts import Config, Ritual, Transition

GLOBAL = Path("/home/me/.config/vekna/config.toml")
PROJECT = Path("/repo/.vekna.toml")


class _Greeting(BaseModel):
    name: str
    loud: bool = False


class _Span(BaseModel):
    start: int
    stop: int

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.stop:
            msg = "start must come before stop"
            raise ValueError(msg)
        return self


async def _never(_: BaseModel) -> Transition:
    await asyncio.sleep(0)
    return Done(None)


GREET = Ritual(
    name="greet", components=_Greeting, run=_never, max_steps=1, exits=(), ends=True
)
SPAN = Ritual(
    name="span", components=_Span, run=_never, max_steps=1, exits=(), ends=True
)


def _config(table: dict[str, object]) -> Config:
    return Config.model_validate({"defaults": {"greet": table}})


class TestDefaults:
    @staticmethod
    def test_a_project_key_overrides_its_global_twin_and_spares_the_rest():
        defaults = Defaults(
            [
                (GLOBAL, _config({"name": "world", "loud": True})),
                (PROJECT, _config({"name": "repo"})),
            ]
        )

        assert defaults.of(GREET) == {
            "name": Default("repo", PROJECT),
            "loud": Default(value=True, source=GLOBAL),
        }

    @staticmethod
    def test_what_was_given_wins_over_a_default():
        defaults = Defaults([(PROJECT, _config({"name": "repo", "loud": True}))])

        assert defaults.components(GREET, {"name": "you"}) == _Greeting(
            name="you", loud=True
        )

    @staticmethod
    def test_a_key_the_ritual_does_not_take_names_the_file_that_set_it():
        defaults = Defaults([(PROJECT, _config({"shout": True}))])

        with pytest.raises(RitualDefinitionError, match=r"\.vekna\.toml.*'shout'"):
            defaults.of(GREET)

    @staticmethod
    def test_a_ritual_no_config_names_has_no_defaults():
        defaults = Defaults([])

        assert defaults.of(GREET) == {}

    # A model-level validator refuses the whole set, and has no flag to name.
    @staticmethod
    def test_a_refusal_of_the_whole_model_names_the_ritual():
        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(SPAN, {"start": 3, "stop": 1})

        assert str(raised.value) == "span: Value error, start must come before stop"

    @staticmethod
    def test_a_config_the_whole_model_refuses_names_its_files():
        defaults = Defaults(
            [
                (GLOBAL, Config.model_validate({"defaults": {"span": {"start": 3}}})),
                (PROJECT, Config.model_validate({"defaults": {"span": {"stop": 1}}})),
            ]
        )

        with pytest.raises(RitualDefinitionError) as raised:
            defaults.of(SPAN)

        assert str(raised.value) == (
            "span: Value error, start must come before stop"
            f" (with [defaults.span] from {GLOBAL}, {PROJECT})"
        )

    @staticmethod
    def test_a_field_the_config_leaves_to_the_flags_is_not_its_refusal():
        defaults = Defaults(
            [(PROJECT, Config.model_validate({"defaults": {"span": {"start": 3}}}))]
        )

        assert defaults.of(SPAN) == {"start": Default(3, PROJECT)}

    # Neither typed nor configured, so not required either: the ritual's own
    # default is what was refused.
    @staticmethod
    def test_a_refused_field_nobody_set_is_named_without_a_value():
        class _Checked(BaseModel):
            mode: int = Field(default="fast", validate_default=True)

        checked = Ritual(
            name="checked",
            components=_Checked,
            run=_never,
            max_steps=1,
            exits=(),
            ends=True,
        )

        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(checked, {})

        assert str(raised.value) == (
            "checked: --mode: Input should be a valid integer,"
            " unable to parse string as an integer"
        )

    # Said as each was set: the config's value with its file, the flag as typed.
    @staticmethod
    def test_every_refusal_at_the_cast_is_said_where_it_was_set():
        defaults = Defaults([(PROJECT, _config({"loud": "very"}))])

        with pytest.raises(RitualDefinitionError) as raised:
            defaults.components(GREET, {"name": ["you"]})

        assert str(raised.value) == (
            "greet: --name ['you']: Input should be a valid string\n"
            f'{PROJECT}: [defaults.greet] loud = "very":'
            " Input should be a valid boolean, unable to interpret input"
        )

    @staticmethod
    def test_a_required_field_nobody_set_is_named_by_its_flag():
        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(GREET, {})

        assert str(raised.value) == "greet: --name is required"

    @staticmethod
    def test_a_flag_the_ritual_does_not_take_names_what_it_does_take():
        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(GREET, {"shout": True, "whisper": True})

        assert str(raised.value) == (
            "greet takes no --shout, --whisper (it takes --name, --loud)"
        )

    @staticmethod
    def test_a_flag_to_a_ritual_taking_none_says_it_takes_nothing():
        silent = Ritual(
            name="silent",
            components=BaseModel,
            run=_never,
            max_steps=1,
            exits=(),
            ends=True,
        )

        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(silent, {"shout": True})

        assert str(raised.value) == "silent takes no --shout (it takes nothing)"

    # A nested refusal keeps its path below the key, so the operator finds it in
    # the value the config set.
    @staticmethod
    def test_a_nested_refusal_in_a_config_names_its_path_under_the_key():
        class _Deep(BaseModel):
            x: int

        class _Outer(BaseModel):
            deep: _Deep

        class _Nested(BaseModel):
            shallow: _Deep
            outer: _Outer

        nested = Ritual(
            name="nested",
            components=_Nested,
            run=_never,
            max_steps=1,
            exits=(),
            ends=True,
        )
        defaults = Defaults(
            [
                (
                    PROJECT,
                    Config.model_validate(
                        {"defaults": {"nested": {"shallow": {}, "outer": {"deep": {}}}}}
                    ),
                )
            ]
        )

        with pytest.raises(RitualDefinitionError) as raised:
            defaults.of(nested)

        assert str(raised.value) == (
            f"{PROJECT}: [defaults.nested] shallow = {{}}: x: Field required\n"
            f'{PROJECT}: [defaults.nested] outer = {{"deep": {{}}}}:'
            " deep.x: Field required"
        )
