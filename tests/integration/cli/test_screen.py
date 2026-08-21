import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from vekna.gates.cli.screen import listing, paint
from vekna.pacts.casts import CastView, RiteStatus, RiteView
from vekna.wire import CastHello, DecideRequested, RiteStarted, RunRecord

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_WIDE_TERMINAL = 120
# How long a rite in these tests takes, once it is finished at all.
_TOOK = 5
_MANY = 15


def _hello() -> CastHello:
    return CastHello(
        cast_id="c1abcdef99",
        project_root="/proj",
        ritual="fix_demo",
        components={},
        started_at=_WHEN,
    )


def _rite(rite_id: str, *, parent_id: str | None) -> RiteView:
    return RiteView(
        started=RiteStarted(
            cast_id="c1abcdef99",
            rite_id=rite_id,
            parent_id=parent_id,
            name=f"rite-{rite_id}",
            category="step",
            started_at=_WHEN,
        )
    )


def _running(ritual: str, *, ago: int) -> CastView:
    return CastView(
        hello=CastHello(
            cast_id=ritual,
            project_root="/proj",
            ritual=ritual,
            components={},
            started_at=_WHEN - timedelta(seconds=ago),
        )
    )


# The rite's name is its id too: a cast in a test has one rite per name, and
# every assertion here is about a name.
def _add(
    view: CastView,
    name: str,
    *,
    ago: int,
    status: RiteStatus = "running",
    category: Literal["step", "medium"] = "step",
) -> None:
    rite = RiteView(
        started=RiteStarted(
            cast_id=view.hello.cast_id,
            rite_id=name,
            parent_id=None,
            name=name,
            category=category,
            started_at=_WHEN - timedelta(seconds=ago),
        )
    )
    rite.status = status
    if status != "running":
        rite.finished_at = _WHEN - timedelta(seconds=ago - _TOOK)
    view.rites[name] = rite


def _step(
    view: CastView, name: str, *, ago: int, status: RiteStatus = "running"
) -> None:
    _add(view, name, ago=ago, status=status)


def _medium(view: CastView, name: str, *, ago: int) -> None:
    _add(view, name, ago=ago, category="medium")


# The listed casts, without the header, the blank lines and the key hints: a
# row is the only thing on the page that opens with the number typed to reach
# it.
_ROW = re.compile(r"^\s*\d+\s+\S")


def _rows(painted: str) -> list[str]:
    return [line for line in painted.splitlines() if _ROW.match(line)]


def _row(painted: str, ritual: str) -> str:
    return next(line for line in _rows(painted) if ritual in line)


@pytest.fixture(name="_tokyo")
def _in_tokyo(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


class TestListing:
    # The journal records UTC, and an operator reading a bare wall clock in
    # another zone has nothing on screen to tell them so.
    @staticmethod
    @pytest.mark.usefixtures("_tokyo")
    def test_the_time_is_the_readers_own():
        line = listing([RunRecord(hello=_hello())])

        assert "2026-01-01 21:00" in line

    @staticmethod
    def test_nothing_recorded_says_so():
        assert listing([]) == "no casts recorded\n"

    # Two rows of the same ritual in the same project, minutes apart, are one
    # piece of work carried on — and nothing said so before.
    @staticmethod
    def test_a_resumed_cast_names_the_one_it_carries_on_from():
        carried = _hello()
        carried.cast_id = "c2beef0011"
        carried.resumed_from = "c1abcdef99"

        line = listing([RunRecord(hello=carried)])

        assert "↳ c1abcdef" in line

    @staticmethod
    def test_a_first_cast_carries_on_from_nothing():
        assert "↳" not in listing([RunRecord(hello=_hello())])


class TestTheList:
    # The reason to look at the view at all: which of the six casts running
    # needs a human, and which is quietly stuck.
    @staticmethod
    def test_a_cast_says_how_long_how_far_and_what_now():
        view = _running("merge_ready", ago=252)
        _step(view, "prepare", ago=250, status="ok")
        _step(view, "gates", ago=180, status="ok")
        _step(view, "land", ago=62)
        _medium(view, "coding", ago=61)

        row = _row(paint(casts=[view], focus=None, now=_WHEN), "merge_ready")

        assert "running" in row
        assert "4m12s" in row
        assert "land · coding" in row
        assert "  2  " in row  # two steps finished, `land` is still going
        assert "1m02s" in row  # and it has been going that long

    # A cast blocked on a person is the whole reason to have the view up.
    @staticmethod
    def test_a_waiting_cast_sorts_above_a_busy_one_and_shows_the_question():
        busy = _running("merge_ready", ago=90)
        asking = _running("triage", ago=30)
        asking.waiting["q1"] = DecideRequested(
            cast_id="triage", request_id="q1", prompt="merge #74 now?"
        )

        listed = _rows(paint(casts=[busy, asking], focus=None, now=_WHEN))

        assert "triage" in listed[0]
        assert "waiting" in listed[0]
        assert "merge #74 now?" in listed[0]
        assert "merge_ready" in listed[1]

    # An aborted cast is the one worth carrying on with, and the id is what
    # carries it on — so the row is the command, not a status to go look up.
    @staticmethod
    def test_an_aborted_cast_shows_how_to_carry_it_on():
        view = _running("fix_demo", ago=764)
        view.status = "disconnected"
        _step(view, "compose", ago=760, status="ok")

        row = _row(paint(casts=[view], focus=None, now=_WHEN), "fix_demo")

        assert "aborted" in row
        assert "vekna cast --continue fix_demo" in row

    # The clock is the cast's, not the reader's: a cast that ended an hour ago
    # ended after however long it took, and counts no further.
    @staticmethod
    def test_a_finished_cast_stops_counting():
        view = _running("ping", ago=3600)
        _step(view, "ping_it", ago=3595, status="ok")
        view.status = "ok"

        row = _row(paint(casts=[view], focus=None, now=_WHEN), "ping")

        assert "done" in row
        # It began an hour ago and its one rite finished ten seconds later, so
        # that is what it took — not the hour since.
        assert "10s" in row

    # A ritual's error runs to four lines of pydantic. In the listing it would
    # reflow every column under it; the row says `failed` and drilling in says
    # why.
    @staticmethod
    def test_the_listing_carries_no_error_text_and_drilling_in_does():
        view = _running("planned", ago=30)
        view.status = "error"
        view.detail = "does not validate:\n  Invalid JSON: expected ident\n  see docs"

        listed = paint(casts=[view], focus=None, now=_WHEN)
        drilled = paint(casts=[view], focus="planned", now=_WHEN)

        assert "failed" in _row(listed, "planned")
        assert "Invalid JSON" not in listed
        assert max(len(line) for line in listed.splitlines()) < _WIDE_TERMINAL
        assert "Invalid JSON" in drilled

    # A daemon left up for a week holds every cast it ever heard.
    @staticmethod
    def test_older_casts_collapse_into_a_count():
        ended = [_running(f"job{n}", ago=60) for n in range(_MANY)]
        for view in ended:
            view.status = "ok"

        painted = paint(casts=ended, focus=None, now=_WHEN)

        assert "vekna — 15 done" in painted
        assert "… 3 older" in painted
        # Newest first, so the three that go are the three oldest.
        assert "job0 " not in painted
        assert "job14" in painted

    # Fifteen casts running at once is exactly when the view has to be read,
    # and none of them is the one that can be dropped for space.
    @staticmethod
    def test_no_running_cast_is_ever_dropped_for_space():
        painted = paint(
            casts=[_running(f"job{n}", ago=60) for n in range(_MANY)],
            focus=None,
            now=_WHEN,
        )

        assert "… " not in painted
        assert len(_rows(painted)) == _MANY

    @staticmethod
    def test_nothing_running_says_where_casts_come_from():
        assert "vekna cast <ritual>" in paint(casts=[], focus=None)


class TestDrilledIn:
    # `parent_id` is whatever a peer wrote on the wire and nothing checks it for
    # loops. Walked recursively, this took the painting task down with it.
    @staticmethod
    def test_a_parent_chain_that_loops_still_paints():
        view = CastView(hello=_hello())
        view.rites["r1"] = _rite("r1", parent_id="r2")
        view.rites["r2"] = _rite("r2", parent_id="r1")

        painted = paint(casts=[view], focus="c1abcdef99")

        assert "rite-r1" in painted
        assert "rite-r2" in painted

    @staticmethod
    def test_a_resumed_cast_names_the_one_it_carries_on_from():
        carried = _hello()
        carried.cast_id = "c2beef0011"
        carried.resumed_from = "c1abcdef99"

        painted = paint(casts=[CastView(hello=carried)], focus="c2beef0011")

        assert "↳ c1abcdef" in painted
