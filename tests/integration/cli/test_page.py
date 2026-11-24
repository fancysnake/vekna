from datetime import UTC, datetime
from typing import cast

import pytest

from vekna.gates.cli.contents import Counts, Entry, Kind
from vekna.gates.cli.page import NO_CAST, head

_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _bare(kind: Kind) -> Entry:
    return Entry(key=f"{kind}:x", kind=kind, name="x", counts=Counts())


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
