from pathlib import Path

from vekna.wire import ConfigLayer, merged_table


class TestConfigLayer:
    @staticmethod
    def test_a_file_is_named_by_its_path():
        layer = ConfigLayer(Path("/repo/.vekna.toml"), {})

        assert layer.source == "/repo/.vekna.toml"
        assert layer.table("defaults.heal") == "/repo/.vekna.toml: [defaults.heal]"

    @staticmethod
    def test_a_project_table_is_named_as_the_file_spells_it():
        layer = ConfigLayer(Path("/me/config.toml"), {}, "mine")

        assert layer.source == "/me/config.toml: [projects.mine]"
        assert layer.table("cabinet") == "/me/config.toml: [projects.mine.cabinet]"


class TestMergedTable:
    @staticmethod
    def test_a_nearer_key_wins_and_inner_tables_merge():
        near = ConfigLayer(
            Path("/near"), {"cabinet": {"gate": "near", "agent": {"effort": "high"}}}
        )
        far = ConfigLayer(
            Path("/far"),
            {
                "cabinet": {
                    "gate": "far",
                    "coverage": "cov",
                    "agent": {"effort": "low", "may_not_run": ["x"]},
                }
            },
        )
        silent = ConfigLayer(Path("/silent"), {"cabinet": 3})

        assert merged_table([near, far, silent], "cabinet") == {
            "gate": "near",
            "coverage": "cov",
            "agent": {"effort": "high", "may_not_run": ["x"]},
        }

    @staticmethod
    def test_an_empty_inner_table_is_kept():
        near = ConfigLayer(Path("/near"), {"cabinet": {"agent": {}}})

        assert merged_table([near], "cabinet") == {"agent": {}}

    @staticmethod
    def test_a_table_nobody_sets_is_empty():
        assert not merged_table([ConfigLayer(Path("/near"), {})], "cabinet")
