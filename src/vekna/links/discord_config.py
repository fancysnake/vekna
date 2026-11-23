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


class _TokenError(Exception):
    pass


# The user's own `[discord]` and the token its file holds, or `None` with the
# reason logged. A project's `.vekna.toml` is not asked: a repository must not
# say where its casts' questions go, or who may answer them. The token is in a
# file because the daemon is started by whichever `vekna` runs first, with
# that shell's environment.
def discord_setup() -> DiscordSetup | None:
    read = read_user_layers(table=_TABLE, model=_File)
    for problem in read.problems:
        _log.warning("%s", problem)
    if (said := _said(read.found)) is None:
        return None
    try:
        token = _token(said)
    except _TokenError as error:
        _log.warning("%s", error)
        return None
    return DiscordSetup(
        token=token, guild=said.guild, category=said.category, allow=said.allow
    )


# Every key is the machine's: only the user's top-level `[discord]` is read.
DISCORD_KEYS = tuple(_Discord.model_fields)


# The token itself is never part of a problem.
def discord_problems() -> list[str]:
    read = read_user_layers(table=_TABLE, model=_File)
    if (said := _said(read.found)) is None:
        return read.problems
    try:
        _token(said)
    except _TokenError as error:
        return [*read.problems, str(error)]
    return read.problems


def _said(found: list[_File]) -> _Discord | None:
    return next((file.discord for file in found if file.discord), None)


def _token(said: _Discord) -> str:
    path = said.token_file or default_config_path().with_name(_BESIDE_CONFIG)
    try:
        token = path.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as error:
        msg = f"Discord is off: its token could not be read: {error}"
        raise _TokenError(msg) from error
    if not token:
        msg = f"Discord is off: {path} is empty"
        raise _TokenError(msg)
    return token
