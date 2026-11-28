import logging
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vekna.pacts.remote import DiscordSetup
from vekna.wire import default_config_path, read_user_layers

_log = logging.getLogger(__name__)
_TABLE = "discord"
_BESIDE_CONFIG = "discord-token"


class _Discord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guild: int
    category: str = "vekna"
    allow: frozenset[int] = Field(min_length=1)
    token_file: Path | None = None


# Only `[discord]` is read here; every other table is somebody else's.
class _File(BaseModel):
    discord: _Discord | None = None


# The user's own `[discord]` and the token its file holds, or `None` with the
# reason logged. A project's `.vekna.toml` is not asked: a repository must not
# say where its casts' questions go, or who may answer them. The token is in a
# file because the daemon is started by whichever `vekna` runs first, with
# that shell's environment.
class ConfigDiscord:
    def __init__(self) -> None:
        # The daemon asks every few seconds: a problem is logged when it
        # appears, not on every look.
        self._said: frozenset[str] = frozenset()

    def setup(self) -> DiscordSetup | None:
        setup, problems = _read()
        for problem in sorted(frozenset(problems) - self._said):
            _log.warning("%s", problem)
        self._said = frozenset(problems)
        return setup


# Every key is the machine's: only the user's top-level `[discord]` is read.
DISCORD_KEYS = tuple(_Discord.model_fields)


# The token itself is never part of a problem.
def discord_problems() -> list[str]:
    return _read()[1]


def _read() -> tuple[DiscordSetup | None, list[str]]:
    read = read_user_layers(table=_TABLE, model=_File)
    said = next((file.discord for file in read.found if file.discord), None)
    if said is None:
        return None, read.problems
    path = said.token_file or default_config_path().with_name(_BESIDE_CONFIG)
    try:
        token = path.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        return None, [
            *read.problems,
            f"Discord is off: its token could not be read: {error}",
        ]
    if not token:
        return None, [*read.problems, f"Discord is off: {path} is empty"]
    setup = DiscordSetup(
        token=token, guild=said.guild, category=said.category, allow=said.allow
    )
    return setup, read.problems
