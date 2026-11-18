from datetime import timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from vekna.wire import read_layers

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
# nearest config layer that says, and `HISTORY_AFTER` when none does. A config
# that will not read is passed over and named in what comes back with it, for
# the window to say: a typo must not keep the window from opening.
def history_after(directory: Path) -> tuple[timedelta, str]:
    files, problems = read_layers(directory=directory, table="window", model=_File)
    ignored = " · ".join(problems)
    for file in files:
        if file.window.history_after is not None:
            return file.window.history_after, ignored
    return HISTORY_AFTER, ignored
