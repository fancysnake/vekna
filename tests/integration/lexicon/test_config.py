import pytest

from vekna.lexicon import RitualDefinitionError
from vekna.lexicon._links.loader import read_configs
from vekna.lexicon._pacts import Config, RitualsConfig, Tome


# The one config a directory with only a `.vekna.toml` reads.
def read_config(config):
    configs = read_configs(config.parent)
    assert len(configs) == 1
    return configs[0][1]


@pytest.fixture(autouse=True)
def _no_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config"))


class TestReadConfig:
    @staticmethod
    def test_reads_modules_and_files(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text(
            '[rituals]\nmodules = ["pkg.rites"]\nfiles = ["rituals.py"]\n'
        )

        assert read_config(config) == Config(
            rituals=RitualsConfig(modules=["pkg.rites"], files=["rituals.py"])
        )

    @staticmethod
    def test_a_missing_rituals_table_reads_as_empty(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text("[other]\nkey = 1\n")

        assert read_config(config) == Config(rituals=RitualsConfig())

    @staticmethod
    def test_a_rituals_key_that_is_not_a_table_is_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('rituals = "nope"\n')

        with pytest.raises(RitualDefinitionError, match=r"\.vekna\.toml"):
            read_config(config)

    @staticmethod
    def test_a_non_string_entry_is_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodules = ["ok", 3]\n')

        with pytest.raises(RitualDefinitionError, match="modules"):
            read_config(config)

    @staticmethod
    def test_a_list_names_each_tome_by_its_top_level_package(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodules = ["cabinet.rituals"]\n')

        assert read_config(config).rituals.modules == [
            Tome(namespace="cabinet", module="cabinet.rituals")
        ]

    @staticmethod
    def test_a_table_names_each_tome_by_its_key(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodules = { cab = "cabinet.rituals" }\n')

        assert read_config(config).rituals.modules == [
            Tome(namespace="cab", module="cabinet.rituals")
        ]

    @staticmethod
    @pytest.mark.parametrize("namespace", ["", "a:b", "my-tome"])
    def test_a_namespace_that_is_not_an_identifier_is_an_error(tmp_path, namespace):
        config = tmp_path / ".vekna.toml"
        config.write_text(f'[rituals]\nmodules = {{ "{namespace}" = "pkg.rites" }}\n')

        with pytest.raises(
            RitualDefinitionError, match=r"(?s)\.vekna\.toml.*identifier"
        ):
            read_config(config)

    @staticmethod
    def test_modules_that_are_neither_a_list_nor_a_table_are_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodules = "pkg.rites"\n')

        with pytest.raises(RitualDefinitionError, match="modules"):
            read_config(config)

    @staticmethod
    def test_a_misspelt_table_and_a_misshapen_value_are_both_named(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text("[ritual]\n[defaults]\nbad = 1\n")

        with pytest.raises(RitualDefinitionError) as raised:
            read_config(config)

        first, second = str(raised.value).splitlines()
        assert first == (
            f"{config}: vekna reads no [ritual] table — did you mean [rituals]?"
        )
        assert second.startswith(f"{config}: ")
        assert "defaults.bad" in second

    @staticmethod
    def test_every_misspelt_table_is_named(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text("[ritual]\n[default]\n")

        with pytest.raises(RitualDefinitionError) as raised:
            read_config(config)

        assert str(raised.value).splitlines() == [
            f"{config}: vekna reads no [ritual] table — did you mean [rituals]?",
            f"{config}: vekna reads no [default] table — did you mean [defaults]?",
        ]

    @staticmethod
    def test_a_misspelt_key_is_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodule = ["pkg.rites"]\n')

        with pytest.raises(
            RitualDefinitionError,
            match=r"rituals\.module: Extra inputs are not permitted",
        ):
            read_config(config)
