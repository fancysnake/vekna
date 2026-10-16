import tomllib
from datetime import date, datetime, time
from pathlib import Path
from typing import TypeAlias

# Every value TOML can hold, which is what `tomllib` types as `Any`.
TomlValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | datetime
    | date
    | time
    | list["TomlValue"]
    | dict[str, "TomlValue"]
)


# Both ends read a config — the cast its `[rituals]`, the daemon its `[circle]`
# — and this is the one module that holds `tomllib`'s `Any`.
def read_toml(path: Path) -> dict[str, TomlValue]:
    with path.open("rb") as handle:
        return tomllib.load(handle)
