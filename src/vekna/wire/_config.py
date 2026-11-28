import logging
import os
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Generic, NamedTuple, TypeVar

from pydantic import BaseModel, ValidationError

from ._refusals import explained
from ._toml import TomlValue, read_toml

_File = TypeVar("_File", bound=BaseModel)

_CONFIG_ENV = "XDG_CONFIG_HOME"
_PROJECT_CONFIG = ".vekna.toml"


# The directory every program of the user's keeps its config under.
def config_home() -> Path:
    if (named := os.environ.get(_CONFIG_ENV)) is not None:
        return Path(named)
    return Path.home() / ".config"


# What the user configured, which is the one thing of vekna's that belongs in
# the config namespace — the journal and the debug log are state and live under
# `default_state_root()`. Here because the cast reads `[rituals]` from it and
# the daemon reads `[circle]`.
def default_config_path() -> Path:
    return config_home() / "vekna" / "config.toml"


# The project's own config, nearest first, as both ends find it.
def project_config_path(directory: Path) -> Path | None:
    for here in (directory, *directory.parents):
        if (found := here / _PROJECT_CONFIG).is_file():
            return found
    return None


# The repository a directory is a tree of, read off the disk the way git lays
# it out, for a config reader that is called where nothing can be awaited. A
# checkout holds its `.git` directory; a linked worktree holds a `.git` file
# naming a directory whose `commondir` points back at the checkout's. Outside
# any repository a directory is its own.
def _repository(directory: Path) -> Path:
    here = directory.resolve()
    for at in (here, *here.parents):
        marker = at / ".git"
        if marker.is_dir():
            return marker
        if marker.is_file():
            return _linked(marker)
    return here


# A directory with no `commondir` is a repository's own: a submodule's, whose
# worktrees point back at it.
def _linked(marker: Path) -> Path:
    try:
        named = marker.read_text(encoding="utf-8").removeprefix("gitdir:").strip()
    except OSError:
        return marker
    git_dir = (marker.parent / named).resolve()
    try:
        common = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return git_dir
    return (git_dir / common).resolve()


# One place a config value can come from: a file, or the table inside the user's
# file that speaks for one project.
class ConfigLayer(NamedTuple):
    path: Path
    tables: dict[str, TomlValue]
    project: str | None = None

    # What an error about the whole layer names.
    @property
    def source(self) -> str:
        if self.project is None:
            return str(self.path)
        return f"{self.path}: [projects.{self.project}]"

    # What an error about one of its tables names, as the file spells it.
    def table(self, name: str) -> str:
        inside = name if self.project is None else f"projects.{self.project}.{name}"
        return f"{self.path}: [{inside}]"


# What a read found, and what it had to leave out and why.
class ConfigRead(NamedTuple):
    layers: list[ConfigLayer]
    problems: list[str]


class TableRead(NamedTuple, Generic[_File]):
    found: list[_File]
    problems: list[str]


# For a reader asked every few seconds: a problem is logged when it appears,
# not on every look.
class ProblemLog:
    def __init__(self, log: logging.Logger) -> None:
        self._log = log
        self._said: frozenset[str] = frozenset()

    def warn(self, problems: Sequence[str]) -> None:
        for problem in sorted(frozenset(problems) - self._said):
            self._log.warning("%s", problem)
        self._said = frozenset(problems)


def _tables(path: Path, problems: list[str]) -> dict[str, TomlValue] | None:
    try:
        return read_toml(path)
    except (OSError, ValueError) as error:
        problems.append(f"{path}: {error}")
        return None


def _user_file(problems: list[str]) -> tuple[Path, dict[str, TomlValue] | None]:
    user = default_config_path()
    return user, _tables(user, problems) if user.is_file() else None


def _everywhere(user: Path, shared: dict[str, TomlValue] | None) -> list[ConfigLayer]:
    if shared is None:
        return []
    return [
        ConfigLayer(user, {key: v for key, v in shared.items() if key != "projects"})
    ]


# The user's project entries that name a checkout: each with its table and the
# checkout's absolute path. An entry that does not is named in `problems`.
def _checkouts(
    *, user: Path, projects: TomlValue, problems: list[str]
) -> Iterator[tuple[str, dict[str, TomlValue], Path]]:
    if not isinstance(projects, dict):
        problems.append(f"{user}: [projects] is not a table")
        return
    for name, table in projects.items():
        source = f"{user}: [projects.{name}]"
        path = table.get("path") if isinstance(table, dict) else None
        if not isinstance(table, dict) or not isinstance(path, str):
            problems.append(f"{source} needs a path, the project's checkout")
            continue
        checkout = Path(path).expanduser()
        if not checkout.is_absolute():
            problems.append(f"{source} path = {path!r} is not absolute")
            continue
        yield name, table, checkout


# A project is a checkout, named by its `path`: the table answers for every
# tree of that repository, so a cast in a pooled worktree reads what a cast
# typed in the checkout reads.
def _project_layers(
    *, user: Path, projects: TomlValue, directory: Path, problems: list[str]
) -> Iterator[ConfigLayer]:
    here = _repository(directory)
    for name, table, checkout in _checkouts(
        user=user, projects=projects, problems=problems
    ):
        if _repository(checkout) == here:
            settings = {key: value for key, value in table.items() if key != "path"}
            yield ConfigLayer(user, settings, name)


# The checkout of every project the user's config names, by its name there. A
# file that will not read, and an entry that names no checkout, are named in
# `problems`.
def project_checkouts(problems: list[str]) -> dict[str, Path]:
    user, shared = _user_file(problems)
    if shared is None or "projects" not in shared:
        return {}
    return {
        name: checkout
        for name, _, checkout in _checkouts(
            user=user, projects=shared["projects"], problems=problems
        )
    }


# The user's project entries whose checkout is gone. An entry that names no
# checkout is `config_layers`' to name, and is passed over here.
def idle_projects() -> list[str]:
    user, shared = _user_file([])
    if shared is None or "projects" not in shared:
        return []
    return [
        f"{user}: [projects.{name}] path = {table['path']!r} does not exist"
        for name, table, checkout in _checkouts(
            user=user, projects=shared["projects"], problems=[]
        )
        if not checkout.exists()
    ]


# Every config that speaks for `directory`, nearest first: the project's own
# `.vekna.toml`, the user's table for this project, then what the user says for
# every project. A file that will not read is left out and named in the second
# list; whether that stops the command is the caller's to say.
def config_layers(directory: Path) -> ConfigRead:
    layers: list[ConfigLayer] = []
    problems: list[str] = []
    user, shared = _user_file(problems)
    if (found := project_config_path(directory)) is not None and (
        tables := _tables(found, problems)
    ) is not None:
        if "projects" in tables:
            problems.append(f"{found}: [projects] is read from {user} only")
        layers.append(ConfigLayer(found, tables))
    if shared is not None and "projects" in shared:
        layers.extend(
            _project_layers(
                user=user,
                projects=shared["projects"],
                directory=directory,
                problems=problems,
            )
        )
    layers.extend(_everywhere(user, shared))
    return ConfigRead(layers, problems)


# What the user says for every project, and nothing a directory could add: for
# a setting that belongs to the machine.
def user_layers() -> ConfigRead:
    problems: list[str] = []
    user, shared = _user_file(problems)
    return ConfigRead(_everywhere(user, shared), problems)


def _validated(read: ConfigRead, *, table: str, model: type[_File]) -> TableRead[_File]:
    found: list[_File] = []
    problems = read.problems
    for layer in read.layers:
        try:
            found.append(model.model_validate(layer.tables))
        except ValidationError as error:
            problems.append(f"{layer.source}: {explained(error)} — [{table}] ignored")
    return TableRead(found, problems)


# The layers read through the one table `model` declares, nearest first. A
# layer that will not read is passed over and named in the second list: a typo
# in a key nobody needed must not stop the daemon or keep the window from
# opening, and the cast that reads the same file refuses it by name.
def read_layers(*, directory: Path, table: str, model: type[_File]) -> TableRead[_File]:
    return _validated(config_layers(directory), table=table, model=model)


def read_user_layers(*, table: str, model: type[_File]) -> TableRead[_File]:
    return _validated(user_layers(), table=table, model=model)


# One layer's word on one key. `layer` indexes the layers the words came from.
class Said(NamedTuple):
    layer: int
    value: TomlValue


# Each key of one table with every layer's word on it that the merge hears, the
# winning word first. A layer whose table is no table is passed over; within a
# table, a nearer value that is no table replaces a farther table whole, and a
# table merges every farther table key by key. `depth` is how many levels are
# merged before a value is taken whole.
def settled(
    said: Sequence[Said], *, depth: int = sys.maxsize
) -> Iterator[tuple[tuple[str, ...], list[Said]]]:
    for name, heard, nested in _named(said, depth=depth):
        if nested:
            for key, inner in settled(heard, depth=depth - 1):
                yield (name, *key), inner
        else:
            yield (name,), heard


# What `settled` drops on the way down: a farther layer's value that is no table
# where a nearer table is merged key by key. Each comes with the nearest word
# that overrides it, so a reader can say the value has no effect.
def overruled(
    said: Sequence[Said], *, depth: int = sys.maxsize
) -> Iterator[tuple[tuple[str, ...], Said, Said]]:
    for name, heard, nested in _named(said, depth=depth):
        if not nested:
            continue
        for one in heard:
            if not isinstance(one.value, dict):
                yield (name,), heard[0], one
        for key, over, lost in overruled(heard, depth=depth - 1):
            yield (name, *key), over, lost


# Each key of the tables among `said`, with every word on it, and whether the
# words are merged further down rather than taken whole.
def _named(
    said: Sequence[Said], *, depth: int
) -> Iterator[tuple[str, list[Said], bool]]:
    tables = [(one.layer, one.value) for one in said if isinstance(one.value, dict)]
    names: dict[str, None] = {}
    names.update((name, None) for _, table in tables for name in table)
    for name in names:
        heard = [Said(layer, table[name]) for layer, table in tables if name in table]
        nested = (
            depth > 1
            and isinstance(heard[0].value, dict)
            and any(isinstance(one.value, dict) and one.value for one in heard)
        )
        yield name, heard, nested


# One table across the layers, a nearer layer's key over a farther one's, and a
# table inside a table merged the same way rather than replaced whole.
def merged_table(layers: list[ConfigLayer], name: str) -> dict[str, TomlValue]:
    merged: dict[str, TomlValue] = {}
    said = [
        Said(index, layer.tables[name])
        for index, layer in enumerate(layers)
        if name in layer.tables
    ]
    for key, heard in settled(said):
        _place(merged, key=key, value=heard[0].value)
    return merged


def _place(
    table: dict[str, TomlValue], *, key: tuple[str, ...], value: TomlValue
) -> None:
    first, *rest = key
    if not rest:
        table[first] = value
        return
    inner = table.get(first)
    if not isinstance(inner, dict):
        inner = {}
        table[first] = inner
    _place(inner, key=tuple(rest), value=value)
