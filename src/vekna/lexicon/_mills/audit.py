import json
import sys
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from vekna.lexicon._pacts import Config
from vekna.wire import ConfigLayer, Said, TomlValue, settled

_RITUALS = "rituals"
_DEFAULTS = "defaults"


# A layer with what it validated as, or None where it did not.
class Audited(NamedTuple):
    layer: ConfigLayer
    config: Config | None


def validated(layers: Sequence[Audited]) -> bool:
    return all(one.config is not None for one in layers)


# `machine` names the root's own tables, each with the keys only the user's
# top-level table may set.
# `rituals` is None when the library did not load whole, so a `[defaults]`
# table naming none of them is not evidence of anything.
# `errors` and `pointless` may name a line twice: the report says each once.
@dataclass(frozen=True, kw_only=True)
class Evidence:
    layers: Sequence[Audited]
    user: Path
    machine: Mapping[str, Collection[str]]
    rituals: Collection[str] | None
    errors: Sequence[str]
    pointless: Sequence[str]


# Each once, in the order first met. `dict.fromkeys` would say it, and is typed
# as holding `Any`.
def _once(names: Iterable[str]) -> list[str]:
    met: dict[str, None] = {}
    met.update((name, None) for name in names)
    return list(met)


def _shown(value: TomlValue) -> str:
    return json.dumps(value, default=str)


class _Report:
    def __init__(self, evidence: Evidence) -> None:
        self._evidence = evidence
        self._layers = [one.layer for one in evidence.layers]
        self.pointless = list(evidence.pointless)

    def _table(self, said: Said, table: str) -> str:
        return self._layers[said.layer].table(table)

    def _users(self, said: Said) -> bool:
        layer = self._layers[said.layer]
        return layer.project is None and layer.path == self._evidence.user

    def _heard(self, *, table: str, key: str, said: list[Said]) -> list[Said]:
        if key not in self._evidence.machine.get(table, ()):
            return said
        self.pointless += [
            f"{self._table(one, table)} {key} is ignored:"
            f" only {self._evidence.user}'s own [{table}] sets it"
            for one in said
            if not self._users(one)
        ]
        return [one for one in said if self._users(one)]

    # What the user's table for the project says to no effect: the project's
    # file says otherwise, or the top level already says the same. A project's
    # file repeating the user's is not one: the file is shared.
    def _idle(self, *, table: str, key: str, heard: list[Said]) -> None:
        for at, one in enumerate(heard):
            if self._layers[one.layer].project is None:
                continue
            said = f"{self._table(one, table)} {key} = {_shown(one.value)}"
            if at:
                self.pointless.append(
                    f"{said} is overridden by {self._table(heard[0], table)}"
                )
            elif heard[1:] and one.value == heard[1].value:
                self.pointless.append(f"{said} repeats {self._table(heard[1], table)}")

    def section(
        self, *, table: str, said: list[Said], depth: int = sys.maxsize, tail: str = ""
    ) -> list[str]:
        lines: list[str] = []
        for path, every in settled(said, depth=depth):
            key = ".".join(path)
            if not (heard := self._heard(table=table, key=key, said=every)):
                continue
            first, *rest = heard
            self._idle(table=table, key=key, heard=heard)
            # A farther layer that says the same is overridden to no effect.
            over = ", ".join(
                f"{one.layer + 1}: {_shown(one.value)}"
                for one in rest
                if one.value != first.value
            )
            lines.append(
                f"  {key} = {_shown(first.value)}  ← {first.layer + 1}"
                + (f" (over {over})" if over else "")
            )
        return [f"[{table}]{tail}", *lines] if lines else []

    # Additive, unlike every other table: each layer's sources are all loaded.
    def rituals(self) -> list[str]:
        named: dict[str, list[int]] = {}
        for index, (_, config) in enumerate(self._evidence.layers):
            if config is None:
                continue
            for namespace, module in config.rituals.modules:
                named.setdefault(f"modules {namespace} = {module}", []).append(index)
            for relative in config.rituals.files:
                source = self._layers[index].path.parent / relative
                named.setdefault(f"files {source}", []).append(index)
        for said, layers in named.items():
            for index in layers if len(layers) > 1 else ():
                if self._layers[index].project is not None:
                    other = next((one for one in layers if one != index), index)
                    self.pointless.append(
                        f"{self._layers[index].table(_RITUALS)} {said}"
                        f" repeats {self._layers[other].table(_RITUALS)}"
                    )
        lines = [
            f"  {said}  ← {', '.join(str(index + 1) for index in layers)}"
            for said, layers in named.items()
        ]
        return [f"[{_RITUALS}]", *lines] if lines else []

    def defaults(self, said: list[Said]) -> list[str]:
        loaded = self._evidence.rituals
        lines: list[str] = []
        # A `defaults` that is no table is passed over, and the validation's to
        # name.
        for (name,), heard in settled(said, depth=1):
            absent = loaded is not None and name not in loaded
            table = f"{_DEFAULTS}.{name}"
            # The user's top-level table speaks for every project, and a ritual
            # this one does not load may be another's.
            self.pointless += [
                f"{self._table(one, table)}: no ritual named {name!r} is loaded here"
                for one in heard
                if absent and not self._users(one)
            ]
            lines += self.section(
                table=table,
                said=heard,
                depth=1,
                tail=" (no such ritual here)" if absent else "",
            )
        return lines

    # Other tools keep tables in the same file, so this is a guess, said as one.
    def _unclaimed(self, name: str, said: list[Said]) -> None:
        layers = self._evidence.layers
        if name in self._evidence.machine or not validated(layers):
            return
        tomes = {
            module.partition(".")[0]
            for one in layers
            if one.config is not None
            for _, module in one.config.rituals.modules
        }
        if name not in tomes:
            self.pointless += [
                f"{self._table(one, name)}: vekna reads no [{name}] and no tome"
                f" named {name!r} is in [rituals] modules — stale, unless another"
                " tool reads it"
                for one in said
            ]

    def tables(self) -> list[str]:
        lines = self.rituals()
        for name in _once(name for layer in self._layers for name in layer.tables):
            said = [
                Said(index, layer.tables[name])
                for index, layer in enumerate(self._layers)
                if name in layer.tables
            ]
            if name == _DEFAULTS:
                lines += self.defaults(said)
            elif name != _RITUALS:
                self._unclaimed(name, said)
                lines += self.section(table=name, said=said)
        return lines


def _listed(title: str, said: Sequence[str]) -> list[str]:
    if not said:
        return []
    return ["", title, *(f"  {line}" for one in said for line in one.splitlines())]


# Every setting with the layer it is taken from, then what is wrong, then what
# sets nothing. Layers are numbered nearest first, and `← 1 (over 3: 2)` reads
# "layer 1 sets it, over the 2 layer 3 says".
def report(evidence: Evidence) -> str:
    made = _Report(evidence)
    tables = made.tables()
    if evidence.layers:
        layers = [
            "layers, nearest first:",
            *(f"  {n}  {one.layer.source}" for n, one in enumerate(evidence.layers, 1)),
        ]
    else:
        nothing = "no config was read: a project's is .vekna.toml, the user's is"
        layers = [f"{nothing} {evidence.user}"]
    errors = _once(evidence.errors)
    pointless = _once(made.pointless)
    clean = not errors and not pointless
    lines = [
        *layers,
        *([""] if tables else []),
        *tables,
        *_listed("errors:", errors),
        *_listed("pointless:", pointless),
        *(["", "no errors, nothing pointless"] if clean else []),
    ]
    return "\n".join(lines) + "\n"
