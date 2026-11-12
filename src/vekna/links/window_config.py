from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from vekna.wire import default_config_path, explained, project_config_path, read_toml

# How long after a cast ends the window moves it to the history view, when
# nothing says otherwise.
HISTORY_AFTER = timedelta(days=1)


# `history_after` is an ISO 8601 duration — "P1D", "PT30M", "PT0S" — which is
# what pydantic reads a `timedelta` from.
class _Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_after: timedelta | None = Field(default=None, ge=timedelta(0))


# Only `[window]` is the window's; every other table is somebody else's.
class _File(BaseModel):
    window: _Window = _Window()


# How long after a cast ends the window moves it to the history view: the
# project's config first, then the user's, and `HISTORY_AFTER` when neither
# says. A config that will not read is passed over and named in what comes back
# with it, for the window to say: a typo must not keep the window from opening.
def history_after(directory: Path) -> tuple[timedelta, str]:
    ignored: list[str] = []
    for path in (project_config_path(directory), default_config_path()):
        if path is None or not path.is_file():
            continue
        try:
            window = _File.model_validate(read_toml(path)).window
        except (OSError, ValueError) as error:
            said = explained(error) if isinstance(error, ValidationError) else error
            ignored.append(f"{path}: {said} — [window] ignored")
            continue
        if window.history_after is not None:
            return window.history_after, " · ".join(ignored)
    return HISTORY_AFTER, " · ".join(ignored)
