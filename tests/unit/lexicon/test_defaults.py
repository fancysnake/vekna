import asyncio
from pathlib import Path

import pytest
from pydantic import BaseModel

from vekna.lexicon import Done, RitualDefinitionError
from vekna.lexicon._mills.defaults import Default, Defaults
from vekna.lexicon._pacts import Config, Ritual, Transition

GLOBAL = Path("/home/me/.config/vekna/config.toml")
PROJECT = Path("/repo/.vekna.toml")


class _Greeting(BaseModel):
    name: str
    loud: bool = False


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
    def test_a_ritual_nobody_set_defaults_for_gets_none():
        defaults = Defaults([])

        assert defaults.of(GREET) == {}
