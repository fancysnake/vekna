from datetime import UTC, datetime
from typing import TYPE_CHECKING

from vekna.mills.liches import Liches
from vekna.pacts.lich import Phylactery, Registry
from vekna.wire import LichDismissRequested, LichFell, LichRose, LichStatus, WireMessage

if TYPE_CHECKING:
    from vekna.pacts.routing import Routed

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


# The registry as a mill sees it: rows in memory, so a test about routing is not
# a test about a file. `LichRegistry` on a real path is the integration test.
class _Rows(Registry):
    def __init__(self, *rows: Phylactery) -> None:
        self.saved = {row.name: row for row in rows}

    def rows(self) -> list[Phylactery]:
        return list(self.saved.values())

    def save(self, row: Phylactery) -> None:
        self.saved[row.name] = row

    def drop(self, name: str) -> None:
        self.saved.pop(name, None)


class _Station:
    def __init__(self) -> None:
        self.sent: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.sent.append(message)


def _rose(name: str = "hollow-vesper", *, root: str = "/proj") -> LichRose:
    return LichRose(lich=name, root=root, pid=4242)


def _row(name: str = "hollow-vesper", *, root: str = "/proj") -> Phylactery:
    return Phylactery(name=name, root=root, created=_WHEN)


class TestRising:
    @staticmethod
    def test_a_lich_that_rises_is_live_and_has_a_row():
        registry = _Rows()
        liches = Liches(registry=registry)

        assert liches.rose(_rose(), _Station()) is None

        assert list(liches.live) == ["hollow-vesper"]
        assert registry.saved["hollow-vesper"].root == "/proj"

    # The row is the lich: raised again it is the same one, so the day it was
    # first raised and the channel it speaks in survive the process that died.
    @staticmethod
    def test_rising_again_keeps_the_row_it_had():
        row = _row()
        row.channel = "9911"
        registry = _Rows(row)
        liches = Liches(registry=registry)

        liches.rose(_rose(), _Station())

        kept = registry.saved["hollow-vesper"]
        assert kept.created == _WHEN
        assert kept.channel == "9911"

    @staticmethod
    def test_a_lich_moved_to_another_root_says_where_it_stands_now():
        registry = _Rows(_row())
        liches = Liches(registry=registry)

        liches.rose(_rose(root="/moved"), _Station())

        assert registry.saved["hollow-vesper"].root == "/moved"

    # Two processes answering to one address is the one thing that cannot be
    # sorted out afterwards: the name is how a command is routed.
    @staticmethod
    def test_a_second_rising_of_one_name_is_refused():
        liches = Liches(registry=_Rows())
        first = _Station()
        liches.rose(_rose(), first)

        refused = liches.rose(_rose(), _Station())

        assert refused == "a lich of that name is already standing"
        assert liches.live["hollow-vesper"].station is first


class TestFalling:
    @staticmethod
    def test_a_dismissed_lich_stops_being_live_and_keeps_no_row():
        registry = _Rows()
        liches = Liches(registry=registry)
        liches.rose(_rose(), _Station())

        liches.apply(LichFell(lich="hollow-vesper", reason="dismissed"))

        assert not liches.live
        # The row goes with the dismissal, not with the process: dropping it is
        # `command`'s job, and this is only the process ending.
        assert "hollow-vesper" in registry.saved

    # A lich whose socket closed under it is dormant, not gone — the row is
    # what a revive reads, and killing the process must not take it.
    @staticmethod
    def test_a_lich_that_vanished_leaves_its_row_behind():
        registry = _Rows()
        liches = Liches(registry=registry)
        liches.rose(_rose(), _Station())

        liches.gone("hollow-vesper")

        assert not liches.live
        assert list(registry.saved) == ["hollow-vesper"]

    @staticmethod
    def test_a_message_for_a_lich_that_is_not_live_is_dropped():
        seen: list[Routed] = []
        liches = Liches(registry=_Rows(), on_routed=seen.append)

        liches.apply(LichStatus(lich="nobody"))

        assert seen[-1].action == "dropped"
        assert seen[-1].subject == "nobody"


class TestStatus:
    @staticmethod
    def test_what_a_lich_says_about_itself_is_held():
        liches = Liches(registry=_Rows())
        liches.rose(_rose(), _Station())

        liches.apply(LichStatus(lich="hollow-vesper", ritual="fix_demo", since=_WHEN))

        said = liches.live["hollow-vesper"].said
        assert said is not None
        assert said.ritual == "fix_demo"


class TestCommands:
    @staticmethod
    def test_a_dismissal_reaches_the_station_and_drops_the_row():
        registry = _Rows()
        liches = Liches(registry=registry)
        station = _Station()
        liches.rose(_rose(), station)

        liches.command(LichDismissRequested(lich="hollow-vesper"))

        assert station.sent == [LichDismissRequested(lich="hollow-vesper")]
        assert not registry.saved

    # There is no process to tell, and dropping the row is the whole of what
    # dismissing a dormant lich means.
    @staticmethod
    def test_a_dormant_lich_is_dismissed_by_its_row_going():
        registry = _Rows(_row())
        seen: list[Routed] = []
        liches = Liches(registry=registry, on_routed=seen.append)

        liches.command(LichDismissRequested(lich="hollow-vesper"))

        assert not registry.saved
        assert seen[-1].action == "dropped"
