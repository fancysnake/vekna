import asyncio
from pathlib import Path
from typing import Self

import pytest
from pydantic import BaseModel, model_validator

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
        span = Ritual(
            name="span", components=_Span, run=_never, max_steps=1, exits=(), ends=True
        )

        with pytest.raises(RitualDefinitionError) as raised:
            Defaults([]).components(span, {"start": 3, "stop": 1})

        assert str(raised.value) == "span: Value error, start must come before stop"
