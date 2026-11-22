import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ConfigDict, PositiveInt
from typing_extensions import override

from vekna.pacts.circle import DEFAULT_PROCESSES, DEFAULT_WORKTREES, Limits
from vekna.wire import TableRead, read_layers, read_user_layers

_T = TypeVar("_T")

_log = logging.getLogger(__name__)


class _Circle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    processes: PositiveInt | None = None
    worktrees: PositiveInt | None = None
    prepare: str | None = None
    base_branch: str | None = None
    coding: PositiveInt | None = None
    total_processes: PositiveInt | None = None
    vigil_processes: PositiveInt | None = None


# Only `[circle]` is the daemon's; every other table is the cast's to read.
class _File(BaseModel):
    circle: _Circle = _Circle()


# A config that will not read is logged and passed over: refusing every cast in
# a project over a typo in a key nobody needed is worse than the default, and
# the cast that reads the same file names it too.
class ConfigLimits(Limits):
    @override
    def processes(self, project_root: str) -> int:
        found = _nearest(Path(project_root), lambda circle: circle.processes)
        return DEFAULT_PROCESSES if found is None else found

    @override
    def worktrees(self, project_root: str) -> int:
        found = _nearest(Path(project_root), lambda circle: circle.worktrees)
        return DEFAULT_WORKTREES if found is None else found

    @override
    def prepare(self, project_root: str) -> str | None:
        return _nearest(Path(project_root), lambda circle: circle.prepare)

    @override
    def base(self, project_root: str) -> str | None:
        return _nearest(Path(project_root), lambda circle: circle.base_branch)

    # The machine's, not a project's: only what the user says for every project.
    @override
    def coding(self) -> int | None:
        return _first(read_user_layers(table="circle", model=_File), lambda c: c.coding)

    # A cast is a process tree of its own, so one per processor is what the
    # machine runs at once without being told.
    @override
    def total(self) -> int:
        found = _first(
            read_user_layers(table="circle", model=_File),
            lambda circle: circle.total_processes,
        )
        return (os.cpu_count() or 1) if found is None else found

    # One slot short of the machine's, so a cast somebody asks for finds room
    # however many vigils are due.
    @override
    def vigils(self) -> int:
        found = _first(
            read_user_layers(table="circle", model=_File),
            lambda circle: circle.vigil_processes,
        )
        return max(self.total() - 1, 1) if found is None else found


def _nearest(directory: Path, key: Callable[[_Circle], _T | None]) -> _T | None:
    found = read_layers(directory=directory, table="circle", model=_File)
    return _first(found, key)


def _first(found: TableRead[_File], key: Callable[[_Circle], _T | None]) -> _T | None:
    for problem in found.problems:
        _log.warning("%s", problem)
    for file in found.found:
        if (value := key(file.circle)) is not None:
            return value
    return None


# What only the user's top-level `[circle]` may set: each is the machine's.
MACHINE_KEYS = ("coding", "total_processes", "vigil_processes")


def circle_problems(directory: Path) -> list[str]:
    return read_layers(directory=directory, table="circle", model=_File).problems
