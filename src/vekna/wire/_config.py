import os
from collections.abc import Iterator
from pathlib import Path
from typing import Generic, NamedTuple, TypeVar

from pydantic import BaseModel, ValidationError

from ._refusals import explained
from ._toml import TomlValue, read_toml

_File = TypeVar("_File", bound=BaseModel)

_CONFIG_ENV = "XDG_CONFIG_HOME"
_PROJECT_CONFIG = ".vekna.toml"


# What the user configured, which is the one thing of vekna's that belongs in
# the config namespace — the journal and the debug log are state and live under
# `default_state_root()`. Here because the cast reads `[rituals]` from it and
# the daemon reads `[circle]`.
def default_config_path() -> Path:
    if (named := os.environ.get(_CONFIG_ENV)) is not None:
        return Path(named) / "vekna" / "config.toml"
    return Path.home() / ".config" / "vekna" / "config.toml"


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


# A project is a checkout, named by its `path`: the table answers for every
# tree of that repository, so a cast in a pooled worktree reads what a cast
# typed in the checkout reads.
def _project_layers(
    *, user: Path, projects: TomlValue, directory: Path, problems: list[str]
) -> Iterator[ConfigLayer]:
    if not isinstance(projects, dict):
        problems.append(f"{user}: [projects] is not a table")
        return
    here = _repository(directory)
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
        if _repository(checkout) == here:
            settings = {key: value for key, value in table.items() if key != "path"}
            yield ConfigLayer(user, settings, name)


# Every config that speaks for `directory`, nearest first: the user's table for
# this project, the project's own `.vekna.toml`, then what the user says for
# every project. A file that will not read is left out and named in the second
# list; whether that stops the command is the caller's to say.
def config_layers(directory: Path) -> ConfigRead:
    layers: list[ConfigLayer] = []
    problems: list[str] = []
    user, shared = _user_file(problems)
    if shared is not None and "projects" in shared:
        layers.extend(
            _project_layers(
                user=user,
                projects=shared["projects"],
                directory=directory,
                problems=problems,
            )
        )
    if (found := project_config_path(directory)) is not None and (
        tables := _tables(found, problems)
    ) is not None:
        if "projects" in tables:
            problems.append(f"{found}: [projects] is read from {user} only")
        layers.append(ConfigLayer(found, tables))
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


# One table across the layers, a nearer layer's key over a farther one's, and a
# table inside a table merged the same way rather than replaced whole.
def merged_table(layers: list[ConfigLayer], name: str) -> dict[str, TomlValue]:
    merged: dict[str, TomlValue] = {}
    for layer in layers:
        if isinstance(table := layer.tables.get(name), dict):
            merged = _over(table, merged)
    return merged


def _over(
    under: dict[str, TomlValue], over: dict[str, TomlValue]
) -> dict[str, TomlValue]:
    merged = dict(under)
    for key, value in over.items():
        below = merged.get(key)
        if isinstance(value, dict) and isinstance(below, dict):
            merged[key] = _over(below, value)
        else:
            merged[key] = value
    return merged
