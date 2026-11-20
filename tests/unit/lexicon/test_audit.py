from dataclasses import replace
from datetime import date
from pathlib import Path

from vekna.lexicon._mills.audit import Audited, Evidence, report
from vekna.lexicon._pacts import Config
from vekna.wire import ConfigLayer, TomlValue

USER = Path("/home/me/.config/vekna/config.toml")
PROJECT = Path("/repo/.vekna.toml")


def _evidence(*layers: ConfigLayer, rituals: tuple[str, ...] | None = ()) -> Evidence:
    return Evidence(
        layers=[
            Audited(layer, Config.model_validate(layer.tables)) for layer in layers
        ],
        user=USER,
        machine={"circle": ("coding",), "window": ()},
        rituals=rituals,
        errors=[],
        pointless=[],
    )


def _tables(said: str) -> str:
    return said.split("\n\n")[1]


def _tome(table: TomlValue) -> dict[str, TomlValue]:
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
    def test_a_line_named_twice_is_said_once():
        evidence = _evidence(ConfigLayer(USER, {}))

        said = report(replace(evidence, errors=["a", "b", "a"], pointless=["c", "c"]))

        assert said.endswith("\nerrors:\n  a\n  b\n\npointless:\n  c\n")

    @staticmethod
    def test_a_layer_whose_table_is_no_table_is_passed_over_as_the_merge_does():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome(5)), ConfigLayer(USER, _tome({"tries": 2}))
            )
        )

        assert _tables(said).endswith("[tome]\n  tries = 2  ← 2")

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
    def test_a_plain_value_under_a_table_the_project_sets_is_pointless():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"agent": {"model": "big"}})),
                ConfigLayer(USER, {"tome": {"agent": "disabled"}}, "repo"),
            )
        )

        assert said.split("\n\n")[2] == (
            "pointless:\n"
            f'  {USER}: [projects.repo.tome] agent = "disabled" is overridden by'
            f" {PROJECT}: [tome] agent\n"
        )

    @staticmethod
    def test_a_module_listed_twice_in_one_table_repeats_that_table():
        said = report(
            _evidence(
                ConfigLayer(
                    USER,
                    {"rituals": {"modules": ["tome.rituals", "tome.rituals"]}},
                    "repo",
                )
            )
        )

        assert said.split("\n\n")[2] == (
            "pointless:\n"
            f"  {USER}: [projects.repo.rituals] modules tome = tome.rituals"
            f" repeats {USER}: [projects.repo.rituals]\n"
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


class TestReportDetails:
    @staticmethod
    def test_a_value_json_cannot_hold_is_shown_as_text():
        said = report(
            _evidence(ConfigLayer(PROJECT, _tome({"since": date(2020, 1, 1)})))
        )

        assert _tables(said).endswith('[tome]\n  since = "2020-01-01"  ← 1')

    @staticmethod
    def test_no_layer_says_where_a_config_would_be_read():
        said = report(replace(_evidence(), layers=[]))

        assert said == (
            "no config was read: a project's is .vekna.toml, the user's is"
            f" {USER}\n\nno errors, nothing pointless\n"
        )

    @staticmethod
    def test_a_machine_key_is_heard_from_the_user_s_own_table_only():
        evidence = _evidence(
            ConfigLayer(PROJECT, {"circle": {"coding": 1, "other": 2}}),
            ConfigLayer(USER, {"circle": {"coding": 3}}, "repo"),
            ConfigLayer(USER, {"circle": {"coding": 4}}),
        )

        said = report(replace(evidence, pointless=["earlier"]))

        assert _tables(said) == "[circle]\n  coding = 4  ← 3\n  other = 2  ← 1"
        assert said.split("\n\n")[2] == (
            "pointless:\n"
            "  earlier\n"
            f"  {PROJECT}: [circle] coding is ignored:"
            f" only {USER}'s own [circle] sets it\n"
            f"  {USER}: [projects.repo.circle] coding is ignored:"
            f" only {USER}'s own [circle] sets it\n"
        )

    @staticmethod
    def test_a_machine_key_only_others_set_leaves_no_table():
        said = report(
            _evidence(ConfigLayer(PROJECT, {"circle": {"coding": 1, "other": 2}}))
        )

        assert _tables(said) == "[circle]\n  other = 2  ← 1"
        assert said.endswith(
            "pointless:\n"
            f"  {PROJECT}: [circle] coding is ignored:"
            f" only {USER}'s own [circle] sets it\n"
        )

    @staticmethod
    def test_a_machine_table_only_others_set_is_not_listed():
        said = report(_evidence(ConfigLayer(PROJECT, {"circle": {"coding": 1}})))

        assert "\n[circle]\n" not in said

    @staticmethod
    def test_every_farther_layer_that_differs_is_named():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"gate": "a"})),
                ConfigLayer(USER, _tome({"gate": "b"}), "repo"),
                ConfigLayer(USER, _tome({"gate": "c"})),
            )
        )

        assert _tables(said).endswith('[tome]\n  gate = "a"  ← 1 (over 2: "b", 3: "c")')

    @staticmethod
    def test_a_plain_value_under_a_nested_table_is_named_by_its_path():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, _tome({"agent": {"model": {"name": "big"}}})),
                ConfigLayer(USER, _tome({"agent": {"model": "small"}}), "repo"),
            )
        )

        assert said.endswith(
            f'  {USER}: [projects.repo.tome] agent.model = "small" is overridden by'
            f" {PROJECT}: [tome] agent.model\n"
        )

    @staticmethod
    def test_a_table_inside_a_default_is_not_merged():
        said = report(
            _evidence(
                ConfigLayer(PROJECT, {"defaults": {"greet": {"to": {"name": "a"}}}}),
                ConfigLayer(USER, {"defaults": {"greet": {"to": "x"}}}, "repo"),
                rituals=("greet",),
            )
        )

        assert said.split("\n\n")[2] == (
            "pointless:\n"
            f'  {USER}: [projects.repo.defaults.greet] to = "x" is overridden by'
            f" {PROJECT}: [defaults.greet]\n"
        )

    @staticmethod
    def test_a_default_for_a_ritual_not_loaded_is_named_where_a_project_sets_it():
        said = report(
            _evidence(
                ConfigLayer(
                    PROJECT,
                    {
                        "rituals": {"files": ["a.py"]},
                        "defaults": {"ghost": {"a": 1}, "greet": {"b": 2}},
                    },
                ),
                ConfigLayer(USER, {"defaults": {"ghost": {"a": 1}}}),
                rituals=("greet",),
            )
        )

        assert _tables(said) == (
            f"[rituals]\n  files {PROJECT.parent / 'a.py'}  ← 1\n"
            "[defaults.ghost] (no such ritual here)\n"
            "  a = 1  ← 1\n"
            "[defaults.greet]\n"
            "  b = 2  ← 1"
        )
        assert said.split("\n\n")[2] == (
            "pointless:\n"
            f"  {PROJECT}: [defaults.ghost]: no ritual named 'ghost'"
            " is loaded here\n"
        )

    @staticmethod
    def test_a_ritual_source_file_is_named_from_its_layer_s_directory():
        said = report(_evidence(ConfigLayer(PROJECT, {"rituals": {"files": ["a.py"]}})))

        assert _tables(said) == f"[rituals]\n  files {PROJECT.parent / 'a.py'}  ← 1"

    @staticmethod
    def test_a_ritual_source_named_once_repeats_nothing():
        said = report(_evidence(ConfigLayer(USER, _tome({}), "repo")))

        assert said.endswith("no errors, nothing pointless\n")

    @staticmethod
    def test_a_layer_that_did_not_validate_does_not_hide_the_next():
        evidence = _evidence(
            ConfigLayer(PROJECT, _tome({"a": 1})), ConfigLayer(USER, _tome({"b": 2}))
        )
        broken = [Audited(evidence.layers[0].layer, None), evidence.layers[1]]

        said = report(replace(evidence, layers=broken))

        assert _tables(said).startswith(
            "[rituals]\n  modules tome = tome.rituals  ← 2\n"
        )

    @staticmethod
    def test_a_table_no_tome_and_no_machine_table_owns_is_stale():
        evidence = _evidence(ConfigLayer(PROJECT, {"stale": {"a": 1}}))

        said = report(replace(evidence, pointless=["earlier"]))

        assert said.split("\n\n")[2] == (
            "pointless:\n  earlier\n"
            f"  {PROJECT}: [stale]: vekna reads no [stale] and no tome named"
            " 'stale' is in [rituals] modules — stale, unless another tool"
            " reads it\n"
        )

    @staticmethod
    def test_a_table_is_no_guess_when_a_layer_did_not_validate():
        evidence = _evidence(ConfigLayer(PROJECT, {"stale": {"a": 1}}))
        broken = [Audited(evidence.layers[0].layer, None)]

        said = report(replace(evidence, layers=broken))

        assert said.endswith("no errors, nothing pointless\n")

    @staticmethod
    def test_a_tome_is_named_by_the_first_part_of_its_module():
        said = report(
            _evidence(
                ConfigLayer(
                    PROJECT,
                    {"rituals": {"modules": ["tome.sub.rituals"]}, "tome": {"a": 1}},
                )
            )
        )

        assert said.endswith("no errors, nothing pointless\n")
