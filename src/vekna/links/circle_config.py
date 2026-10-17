from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, PositiveInt, ValidationError

from vekna.pacts.circle import DEFAULT_PROCESSES, DEFAULT_WORKTREES, Limits
from vekna.wire import default_config_path, project_config_path, read_toml

_T = TypeVar("_T")


class _Circle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processes: PositiveInt | None = None
    worktrees: PositiveInt | None = None
    prepare: str | None = None
    coding: PositiveInt | None = None


# Only `[circle]` is the daemon's; every other table is the cast's to read.
class _File(BaseModel):
    circle: _Circle = _Circle()


# A config that will not read is said where the daemon says things and passed
# over: refusing every cast in a project over a typo in a key nobody needed is
# worse than the default, and the cast that reads the same file names it too.
class ConfigLimits(Limits):
    def __init__(self, *, say: Callable[[str], None]) -> None:
        self._say = say

    def processes(self, project_root: str) -> int:
        found = self._nearest(project_root, lambda circle: circle.processes)
        return DEFAULT_PROCESSES if found is None else found

    def worktrees(self, project_root: str) -> int:
        found = self._nearest(project_root, lambda circle: circle.worktrees)
        return DEFAULT_WORKTREES if found is None else found

    def prepare(self, project_root: str) -> str | None:
        return self._nearest(project_root, lambda circle: circle.prepare)

    def coding(self) -> int | None:
        return self._read(default_config_path()).coding

    # The project's config first, then the user's.
    def _nearest(
        self, project_root: str, key: Callable[[_Circle], _T | None]
    ) -> _T | None:
        for found in (project_config_path(Path(project_root)), default_config_path()):
            if (value := key(self._read(found))) is not None:
                return value
        return None

    def _read(self, path: Path | None) -> _Circle:
        if path is None or not path.is_file():
            return _Circle()
        try:
            return _File.model_validate(read_toml(path)).circle
        except (OSError, ValueError, ValidationError) as error:
            self._say(f"{path}: {error} — [circle] ignored")
            return _Circle()
