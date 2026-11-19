from pathlib import Path

from vekna.lexicon._mills.audit import Evidence, report
from vekna.lexicon._pacts import Config
from vekna.wire import ConfigLayer, TomlValue

USER = Path("/home/me/.config/vekna/config.toml")
PROJECT = Path("/repo/.vekna.toml")


def _evidence(*layers: ConfigLayer, rituals: tuple[str, ...] | None = ()) -> Evidence:
    return Evidence(
        layers=layers,
        configs=[Config.model_validate(layer.tables) for layer in layers],
        user=USER,
        machine={"circle": ("coding",), "window": ()},
        rituals=rituals,
        errors=[],
        pointless=[],
    )


def _tables(said: str) -> str:
    return said.split("\n\n")[1]


def _tome(table: dict[str, TomlValue]) -> dict[str, TomlValue]:
    return {"rituals": {"modules": ["tome.rituals"]}, "tome": table}


class TestReport:
    @staticmethod
    def test_a_table_inside_a_table_is_merged_key_by_key():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"agent": {"model": "big"}})),
                ConfigLayer(USER, _tome({"agent": {"model": "small", "tries": 2}})),
            )
        )

        assert _tables(said) == (
            "[rituals]\n"
            "  modules tome = tome.rituals  ← 1, 2\n"
            "[tome]\n"
            '  agent.model = "big"  ← 1 (over 2: "small")\n'
            "  agent.tries = 2  ← 2"
        )

    @staticmethod
    def test_a_value_over_a_table_replaces_it_whole():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"agent": False})),
                ConfigLayer(USER, _tome({"agent": {"tries": 2}})),
            )
        )

        assert _tables(said).endswith(
            '[tome]\n  agent = false  ← 1 (over 2: {"tries": 2})'
        )

    @staticmethod
    def test_a_default_holding_a_table_is_replaced_whole():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, {"defaults": {"greet": {"to": {"name": "a"}}}}),
                ConfigLayer(USER, {"defaults": {"greet": {"to": {"loud": True}}}}),
                rituals=("greet",),
            )
        )

        assert _tables(said) == (
            '[defaults.greet]\n  to = {"name": "a"}  ← 1 (over 2: {"loud": true})'
        )

    @staticmethod
    def test_the_user_s_table_for_the_project_that_changes_nothing_is_pointless():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"gate": "lint"})),
                ConfigLayer(USER, _tome({"gate": "all", "push": True}), "repo"),
                ConfigLayer(USER, _tome({"push": True})),
            )
        )

        assert said.split("\n\n")[2] == (
            "pointless:\n"
            f"  {USER}: [projects.repo.rituals] modules tome = tome.rituals"
            f" repeats {PROJECT}: [rituals]\n"
            f'  {USER}: [projects.repo.tome] gate = "all" is overridden by'
            f" {PROJECT}: [tome]\n"
            f"  {USER}: [projects.repo.tome] push = true repeats {USER}: [tome]\n"
        )

    @staticmethod
    def test_the_user_s_table_for_the_project_that_wins_is_not_pointless():
        said = report(
            _evidence(
                ConfigLayer(USER, {"tome": {"push": False}}, "repo"),
                ConfigLayer(USER, _tome({"push": True})),
            )
        )

        assert said.endswith("no errors, nothing pointless\n")

    @staticmethod
    def test_defaults_are_not_called_unused_when_the_rituals_did_not_load():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, {"defaults": {"ghost": {"key": 1}}}), rituals=None
            )
        )

        assert said == (
            "layers, nearest first:\n"
            f"  1  {PROJECT}\n"
            "\n"
            "[defaults.ghost]\n"
            "  key = 1  ← 1\n"
            "\n"
            "no errors, nothing pointless\n"
        )
