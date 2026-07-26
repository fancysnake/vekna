from vekna.lexicon._links.loader import read_config
from vekna.lexicon._pacts import Config, RitualsConfig


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

        assert read_config(config) == Config(rituals=None)

    @staticmethod
    def test_a_rituals_key_that_is_not_a_table_is_ignored(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('rituals = "nope"\n')

        assert read_config(config) is None

    @staticmethod
    def test_non_string_entries_fail_parse(tmp_path):
        config = tmp_path / ".vekna.toml"
        config.write_text('[rituals]\nmodules = ["ok", 3]\nfiles = [true, "r.py"]\n')

        assert read_config(config) is None
