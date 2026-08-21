from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.links.registry import LichRegistry
from vekna.pacts.lich import Phylactery, RegistryUnreadableError

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _row(name: str = "hollow-vesper", *, root: str = "/proj") -> Phylactery:
    return Phylactery(name=name, root=root, created=_WHEN)


class TestRows:
    @staticmethod
    def test_nothing_written_yet_is_no_liches(tmp_path: Path):
        assert LichRegistry(tmp_path).rows() == []

    @staticmethod
    def test_a_saved_row_comes_back_whole(tmp_path: Path):
        registry = LichRegistry(tmp_path)
        saved = _row()
        saved.last_cast = "c1abcdef"
        saved.channel = "9911"

        registry.save(saved)

        assert LichRegistry(tmp_path).rows() == [saved]

    # The row is the lich; a lich rising again is that row updated, and a second
    # row of the same name would be a second station answering to one address.
    @staticmethod
    def test_saving_a_name_twice_updates_the_row_it_already_had(tmp_path: Path):
        registry = LichRegistry(tmp_path)
        registry.save(_row())
        registry.save(_row("ashen-quill"))

        risen = _row()
        risen.last_cast = "c2beef00"
        registry.save(risen)

        rows = registry.rows()
        assert [row.name for row in rows] == ["ashen-quill", "hollow-vesper"]
        assert rows[-1].last_cast == "c2beef00"

    @staticmethod
    def test_dismissing_drops_the_row_and_leaves_the_rest(tmp_path: Path):
        registry = LichRegistry(tmp_path)
        registry.save(_row())
        registry.save(_row("ashen-quill"))

        registry.drop("hollow-vesper")

        assert [row.name for row in registry.rows()] == ["ashen-quill"]

    # `dismiss` is what an operator types to be rid of a lich, and a name that
    # is already gone is the state they were after.
    @staticmethod
    def test_dropping_a_name_nobody_holds_is_not_an_error(tmp_path: Path):
        registry = LichRegistry(tmp_path)
        registry.save(_row())

        registry.drop("nobody")

        assert [row.name for row in registry.rows()] == ["hollow-vesper"]

    @staticmethod
    def test_the_registry_is_written_where_the_journal_lives(tmp_path: Path):
        LichRegistry(tmp_path / "state").save(_row())

        assert (tmp_path / "state" / "liches.json").is_file()

    # Every lich is in this one file, so a torn one is not a row lost the way a
    # torn `run.json` is — read as empty it hands out a name somebody holds.
    @staticmethod
    def test_a_file_that_will_not_parse_says_so_and_names_itself(tmp_path: Path):
        (tmp_path / "liches.json").write_text('[{"name": "hollow-vesper"}]')

        with pytest.raises(
            RegistryUnreadableError, match=r"liches\.json will not parse"
        ):
            LichRegistry(tmp_path).rows()

    @staticmethod
    def test_a_half_written_registry_is_never_what_is_read(tmp_path: Path):
        registry = LichRegistry(tmp_path)
        registry.save(_row())

        registry.save(_row("ashen-quill"))

        assert not list(tmp_path.glob("*.part"))
        assert [row.name for row in registry.rows()] == ["hollow-vesper", "ashen-quill"]
