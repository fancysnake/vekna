from pathlib import Path

from pydantic import RootModel, ValidationError

from vekna.pacts.lich import Phylactery, Registry, RegistryUnreadableError

_LICHES = "liches.json"
_HALF = ".part"


class _Rows(RootModel[list[Phylactery]]):
    root: list[Phylactery]


# Every lich this account has ever raised, in one file beside `runs/`. One file
# and not a directory of them: the whole registry is read on every command that
# names a lich, and it is a handful of rows for as long as a person is the one
# raising them.
# ponytail: rewritten whole on every save. A row-per-file layout is the upgrade
# if a machine ever holds enough liches for that to show up.
class LichRegistry(Registry):
    def __init__(self, root: Path) -> None:
        self._path = root / _LICHES

    def rows(self) -> list[Phylactery]:
        if not self._path.is_file():
            return []
        try:
            return list(_Rows.model_validate_json(self._path.read_bytes()).root)
        except ValidationError as error:
            raise RegistryUnreadableError(self._path, str(error)) from error

    # By name, and in place: a lich rising again is the row it already had, with
    # whatever has changed since written onto it.
    def save(self, row: Phylactery) -> None:
        kept = [found for found in self.rows() if found.name != row.name]
        self._write([*kept, row])

    # Dropping one that is not there is not an error: `dismiss` is what an
    # operator types to be rid of a lich, and being rid of it is the state they
    # are after either way.
    def drop(self, name: str) -> None:
        kept = [found for found in self.rows() if found.name != name]
        self._write(kept)

    # Written beside itself and moved into place, because a plain write
    # truncates first: a daemon killed between the two would leave half a
    # registry where every lich lives. `os.replace` is atomic within a
    # directory, so what is there is either the last set of rows or this one.
    def _write(self, rows: list[Phylactery]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        half = self._path.with_suffix(_HALF)
        half.write_text(_Rows(rows).model_dump_json(indent=2))
        half.replace(self._path)
