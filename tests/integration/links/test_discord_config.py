import logging
from pathlib import Path

import pytest

from vekna.links.discord_config import DISCORD_KEYS, ConfigDiscord, discord_problems
from vekna.pacts.remote import DiscordSetup

_GUILD = 100
_OPERATOR = 7
_TABLE = f"[discord]\nguild = {_GUILD}\nallow = [{_OPERATOR}]\n"


@pytest.fixture(name="config")
def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    (tmp_path / "config" / "vekna").mkdir(parents=True)
    return tmp_path / "config" / "vekna" / "config.toml"


def _warned(caplog: pytest.LogCaptureFixture) -> list[str]:
    assert all(record.levelno == logging.WARNING for record in caplog.records)
    return [record.getMessage() for record in caplog.records]


class TestDiscordSetup:
    @staticmethod
    def test_no_table_is_no_discord_and_nothing_said(
        config: Path, caplog: pytest.LogCaptureFixture
    ):
        config.write_text("[circle]\nprocesses = 2\n", encoding="utf-8")

        assert ConfigDiscord().setup() is None
        assert discord_problems() == []
        assert not caplog.records

    @staticmethod
    def test_the_token_is_read_from_the_file_beside_the_config(
        config: Path, caplog: pytest.LogCaptureFixture
    ):
        config.write_text(_TABLE, encoding="utf-8")
        config.with_name("discord-token").write_text("s3cret\n", encoding="utf-8")

        assert ConfigDiscord().setup() == DiscordSetup(
            token="s3cret", guild=_GUILD, category="vekna", allow=frozenset({_OPERATOR})
        )
        assert discord_problems() == []
        assert not caplog.records

    @staticmethod
    def test_a_token_file_and_a_category_can_be_named(
        config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "bot").write_text("t0ken", encoding="utf-8")
        config.write_text(
            _TABLE + 'category = "casts"\ntoken_file = "~/bot"\n', encoding="utf-8"
        )

        assert ConfigDiscord().setup() == DiscordSetup(
            token="t0ken", guild=_GUILD, category="casts", allow=frozenset({_OPERATOR})
        )

    @staticmethod
    def test_a_token_that_cannot_be_read_or_is_empty_is_said_and_audited(
        config: Path, caplog: pytest.LogCaptureFixture
    ):
        config.write_text(_TABLE, encoding="utf-8")
        token = config.with_name("discord-token")
        audited: list[str] = []

        for content in (None, b"\xff\xfe", b"\n"):
            if content is not None:
                token.write_bytes(content)
            assert ConfigDiscord().setup() is None
            audited += discord_problems()

        assert (
            _warned(caplog)
            == audited
            == [
                (
                    "Discord is off: its token could not be read:"
                    f" [Errno 2] No such file or directory: '{token}'"
                ),
                (
                    "Discord is off: its token could not be read: 'utf-8' codec"
                    " can't decode byte 0xff in position 0: invalid start byte"
                ),
                f"Discord is off: {token} is empty",
            ]
        )

    @staticmethod
    @pytest.mark.parametrize(
        ("table", "problem"),
        [
            (f"[discord]\nguild = {_GUILD}\nallow = []\n", "discord.allow"),
            (f"[discord]\nallow = [{_OPERATOR}]\n", "discord.guild"),
            (_TABLE + 'token = "s3cret"\n', "discord.token"),
        ],
    )
    def test_a_table_that_will_not_read_is_said_and_discord_is_off(
        config: Path, caplog: pytest.LogCaptureFixture, table: str, problem: str
    ):
        config.write_text(table, encoding="utf-8")
        config.with_name("discord-token").write_text("s3cret", encoding="utf-8")

        assert ConfigDiscord().setup() is None
        [said] = discord_problems()
        assert said.startswith(f"{config}: ")
        assert problem in said
        assert said.endswith("— [discord] ignored")
        assert _warned(caplog) == [said]

    @staticmethod
    def test_a_problem_is_said_when_it_appears_not_on_every_look(
        config: Path, caplog: pytest.LogCaptureFixture
    ):
        config.write_text(_TABLE, encoding="utf-8")
        token = config.with_name("discord-token")
        book = ConfigDiscord()

        assert book.setup() is None
        assert book.setup() is None
        token.write_text("s3cret", encoding="utf-8")
        assert book.setup() is not None
        token.unlink()
        assert book.setup() is None

        missing = (
            "Discord is off: its token could not be read:"
            f" [Errno 2] No such file or directory: '{token}'"
        )
        assert _warned(caplog) == [missing, missing]

    @staticmethod
    def test_a_projects_own_table_is_not_read(
        config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        config.write_text(f'[projects.app]\npath = "{tmp_path}"\n', encoding="utf-8")
        (tmp_path / ".vekna.toml").write_text(_TABLE, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        assert ConfigDiscord().setup() is None
        assert discord_problems() == []

    @staticmethod
    def test_every_key_is_the_machines():
        assert DISCORD_KEYS == ("guild", "category", "allow", "token_file")
