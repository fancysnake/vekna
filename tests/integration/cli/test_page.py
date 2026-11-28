from datetime import UTC, datetime
from typing import cast

import pytest

from vekna.gates.cli.contents import Counts, Entry, Kind
from vekna.gates.cli.page import NO_CAST, cast_output, head
from vekna.pacts.casts import CastView, RiteView
from vekna.wire import CastHello, RiteStarted

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _bare(kind: Kind) -> Entry:
    return Entry(key=f"{kind}:x", kind=kind, name="x", counts=Counts())


def _rite(rite_id: str, *, parent_id: str | None) -> RiteView:
    return RiteView(
        started=RiteStarted(
            cast_id="c1",
            rite_id=rite_id,
            parent_id=parent_id,
            name=f"rite-{rite_id}",
            category="step",
            started_at=_NOW,
        )
    )


class TestHead:
    @staticmethod
    @pytest.mark.parametrize("kind", ["cast", "more", "rite"])
    def test_a_line_of_a_cast_with_no_cast_behind_it_says_there_is_none(kind: Kind):
        page = head(_bare(kind), branches={}, now=_NOW)

        assert page.plain == NO_CAST

    @staticmethod
    def test_a_line_of_a_kind_the_page_does_not_know_is_refused():
        entry = _bare(cast("Kind", "unheard"))

        with pytest.raises(AssertionError, match="unheard"):
            head(entry, branches={}, now=_NOW)


class TestCastOutput:
    @staticmethod
    def test_a_rite_with_no_parent_is_not_under_a_rite_with_an_empty_id():
        view = CastView(
            hello=CastHello(
                cast_id="c1",
                project_root="/proj",
                project="/proj/.git",
                ritual="demo",
                components={},
                started_at=_NOW,
            )
        )
        picked = _rite("", parent_id=None)
        view.rites[""] = picked
        view.rites["r1"] = stray = _rite("r1", parent_id=None)
        stray.lines.append((False, "unrelated"))

        assert cast_output(view, picked) == []
