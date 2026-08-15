import pytest

from vekna.lexicon import RitualDefinitionError
from vekna.lexicon._links.loader import read_config
from vekna.lexicon._pacts import Config, NotifyConfig, RitualsConfig


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
    def test_a_misspelt_key_is_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodule = ["pkg.rites"]\n')

        with pytest.raises(RitualDefinitionError, match="extra"):
            read_config(config)


class TestNotifyConfig:
    @staticmethod
    def test_reads_the_events_to_notify_on(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[notify]\non = ["done", "failed"]\n')

        assert read_config(config).notify == NotifyConfig(on=["done", "failed"])

    @staticmethod
    def test_every_event_notifies_by_default(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nfiles = ["rituals.py"]\n')

        assert read_config(config).notify == NotifyConfig(
            on=["decide", "done", "failed"]
        )

    @staticmethod
    def test_an_unknown_event_is_an_error(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[notify]\non = ["finished"]\n')

        with pytest.raises(RitualDefinitionError, match="finished"):
            read_config(config)
