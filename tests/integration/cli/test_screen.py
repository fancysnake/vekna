import time
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from vekna.gates.cli.screen import listing, paint
from vekna.pacts.casts import CastView, RiteView
from vekna.wire import CastHello, RiteStarted, RunRecord

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


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
