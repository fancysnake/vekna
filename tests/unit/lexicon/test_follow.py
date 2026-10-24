from datetime import UTC, datetime

from vekna.lexicon._mills.follow import Lineage
from vekna.wire import CastGoodbye, CastHello

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _hello(cast_id: str, *, by: str | None) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        project="/proj/.git",
        ritual="ci_watch",
        components={},
        started_at=_WHEN,
        enqueued_by=by,
    )


class TestDescends:
    @staticmethod
    def test_a_cast_queued_by_one_queued_by_the_root_is_the_root_s():
        lineage = Lineage("root")
        lineage.heard(_hello("child", by="root"))
        lineage.heard(_hello("grandchild", by="child"))
        lineage.heard(_hello("stranger", by=None))

        assert lineage.descends("child")
        assert lineage.descends("grandchild")
        assert not lineage.descends("stranger")
        assert not lineage.descends("root")

    @staticmethod
    def test_a_loop_in_the_parents_ends_the_walk():
        lineage = Lineage("root")
        lineage.heard(_hello("a", by="b"))
        lineage.heard(_hello("b", by="a"))

        assert not lineage.descends("a")


class TestSettled:
    @staticmethod
    def test_nothing_queued_is_settled_at_once():
        assert Lineage("root").settled

    @staticmethod
    def test_a_queued_cast_not_heard_of_yet_holds_it_open():
        lineage = Lineage("root")

        lineage.expect("child")

        assert not lineage.settled

    @staticmethod
    def test_every_descendant_ending_settles_it_and_says_how():
        lineage = Lineage("root")
        lineage.expect("child")
        lineage.heard(_hello("child", by="root"))
        lineage.heard(_hello("grandchild", by="child"))
        lineage.heard(CastGoodbye(cast_id="child", status="ok"))
        assert not lineage.settled

        lineage.heard(CastGoodbye(cast_id="grandchild", status="error"))

        assert lineage.settled
        assert lineage.failed

    @staticmethod
    def test_a_stranger_ending_is_not_counted():
        lineage = Lineage("root")
        lineage.heard(_hello("stranger", by=None))

        lineage.heard(CastGoodbye(cast_id="stranger", status="error"))

        assert lineage.settled
        assert not lineage.failed
