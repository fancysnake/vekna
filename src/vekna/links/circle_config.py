from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, PositiveInt

from vekna.pacts.circle import DEFAULT_PROCESSES, Limits
from vekna.wire import default_config_path, project_config_path, read_toml


class _Circle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processes: PositiveInt | None = None
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
        for found in (project_config_path(Path(project_root)), default_config_path()):
            if (processes := self._read(found).processes) is not None:
                return processes
        return DEFAULT_PROCESSES

    def coding(self) -> int | None:
        return self._read(default_config_path()).coding

    def _read(self, path: Path | None) -> _Circle:
        if path is None or not path.is_file():
            return _Circle()
        try:
            return _File.model_validate(read_toml(path)).circle
        except (OSError, ValueError) as error:
            self._say(f"{path}: {error} — [circle] ignored")
            return _Circle()
