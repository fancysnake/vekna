import io
from datetime import UTC, datetime

from typing_extensions import override

from vekna.lexicon._links.standalone import Tail
from vekna.lexicon._links.turns import Turns
from vekna.lexicon._mills.follow import Lineage
from vekna.lexicon._pacts import RiteBegan, RiteEnded
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

    @staticmethod
    def test_every_descendant_ending_ok_has_not_failed():
        lineage = Lineage("root")
        lineage.expect("child")
        lineage.heard(_hello("child", by="root"))

        lineage.heard(CastGoodbye(cast_id="child", status="ok"))

        assert lineage.settled
        assert not lineage.failed


# Output that is a terminal, which a string buffer never is.
class _Terminal(io.StringIO):
    @override
    def isatty(self) -> bool:
        return True


def _began(rite_id: str = "r1") -> RiteBegan:
    return RiteBegan(
        rite_id=rite_id, parent_id=None, name="watch", category="step", started_at=_WHEN
    )


def _ended(rite_id: str = "r1") -> RiteEnded:
    return RiteEnded(
        rite_id=rite_id, status="ok", result=None, finished_at=_WHEN, error=None
    )


class TestTurns:
    @staticmethod
    def test_the_typed_cast_speaks_first_under_no_name():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")

        turns.typed.write("listing\n")

        assert out.getvalue() == "listing\n"

    @staticmethod
    def test_a_cast_is_named_where_it_takes_over_and_not_again():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")

        turns.render("c1", _began())
        turns.render("c1", _ended())

        assert out.getvalue() == "── ci_watch child000 ──\n▶ watch\n✓ watch\n"

    @staticmethod
    def test_the_typed_cast_is_named_once_another_has_spoken():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")
        turns.render("c1", _began())

        turns.typed.write("back\n")

        assert out.getvalue() == (
            "── ci_watch child000 ──\n▶ watch\n── sweep root0000 ──\nback\n"
        )

    @staticmethod
    def test_a_name_and_a_notice_follow_an_unfinished_line_on_a_row_of_their_own():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")

        turns.typed.write("progress")
        turns.render("c1", _began())
        turns.typed.write("again")
        turns.ended(cast_id="c1", status="ok", detail=None)

        assert out.getvalue() == (
            "progress\n── ci_watch child000 ──\n▶ watch\n"
            "── sweep root0000 ──\nagain\n[ci_watch child000] ✓ done\n"
        )

    @staticmethod
    def test_an_empty_write_takes_nothing_over():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")
        turns.render("c1", _began())

        turns.typed.write("")
        turns.render("c1", _ended())

        assert out.getvalue() == "── ci_watch child000 ──\n▶ watch\n✓ watch\n"

    @staticmethod
    def test_a_rite_nothing_printed_inside_ends_on_its_own_line_at_a_terminal():
        out = _Terminal()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")

        turns.render("c1", _began())
        turns.render("c1", _ended())

        assert out.getvalue() == (
            "── ci_watch child000 ──\n▶ watch\n\x1b[1A\r\x1b[J✓ watch\n"
        )

    @staticmethod
    def test_a_rite_another_cast_spoke_inside_ends_on_a_line_of_its_own():
        out = _Terminal()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")
        turns.render("c1", _began())
        turns.typed.write("back\n")

        turns.render("c1", _ended())

        assert out.getvalue() == (
            "── ci_watch child000 ──\n▶ watch\n── sweep root0000 ──\nback\n"
            "── ci_watch child000 ──\n✓ watch\n"
        )

    @staticmethod
    def test_whether_it_is_a_terminal_is_the_terminal_s_answer():
        assert Turns(Tail(_Terminal()), typed="sweep root0000").typed.isatty()
        assert not Turns(Tail(io.StringIO()), typed="sweep root0000").typed.isatty()

    @staticmethod
    def test_how_a_cast_ended_is_said_with_its_name():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")
        turns.entered(cast_id="c1", label="ci_watch child000")
        turns.entered(cast_id="c2", label="pr_fix child111")

        turns.ended(cast_id="c1", status="ok", detail=None)
        turns.ended(cast_id="c2", status="error", detail="no tree")

        assert out.getvalue() == (
            "[ci_watch child000] ✓ done\n[pr_fix child111] ✗ failed: no tree\n"
        )

    @staticmethod
    def test_a_notice_names_its_cast_and_takes_nothing_over():
        out = io.StringIO()
        turns = Turns(Tail(out), typed="sweep root0000")

        turns.say(cast_id="c1", label="ci_watch child000", line="⏸ push?")
        turns.typed.write("on\n")

        assert out.getvalue() == "[ci_watch child000] ⏸ push?\non\n"
