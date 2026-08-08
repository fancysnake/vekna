import hashlib
from pathlib import Path

import pytest

from rituals.review import (
    Diff,
    Finding,
    Judgement,
    Review,
    ReviewRequest,
    collect,
    judge,
    review,
)
from vekna.lexicon import RitualError, done, goto
from vekna.trial import Trial

_DIFF = "diff --git a/x.py b/x.py\n+broken()\n"
_FINDING = Finding(
    where="x.py:1", what="calls a thing that is not there", severity="blocker"
)


def _pinned(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class TestCollect:
    @staticmethod
    def test_the_diff_is_read_against_the_base_and_pinned_by_content(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="git diff main...HEAD", stdout=_DIFF)

        transition = trial.walk(collect, ReviewRequest(base="main"))

        assert transition == goto(
            judge, Diff(base="main", text=_DIFF, focus="", pinned=_pinned(_DIFF))
        )

    @staticmethod
    def test_only_narrows_the_diff_to_one_file(trial: Trial) -> None:
        trial.shell.replies(when="git diff main...HEAD -- *", stdout=_DIFF)
        here = Path(__file__)

        trial.walk(collect, ReviewRequest(base="main", only=here))

        assert trial.shell.commands == [f"git diff main...HEAD -- {here}"]

    # Nothing changed is an answer, and not one worth paying an agent for.
    @staticmethod
    def test_an_empty_diff_ships_without_reaching_an_agent(trial: Trial) -> None:
        trial.shell.replies(when="git diff*", stdout="   \n")

        transition = trial.walk(collect, ReviewRequest(base="main"))

        assert transition == done(Review(base="main", verdict="ship", findings=[]))
        assert not trial.coding.calls

    @staticmethod
    def test_a_base_git_cannot_resolve_says_so_rather_than_reviewing_nothing(
        trial: Trial,
    ) -> None:
        trial.shell.replies(
            when="git diff nope...HEAD", exit_code=128, stderr="bad revision 'nope'\n"
        )

        with pytest.raises(RitualError, match="git diff against 'nope' failed"):
            trial.walk(collect, ReviewRequest(base="nope"))


class TestJudge:
    @staticmethod
    def test_the_agent_s_verdict_is_carried_out_with_the_ritual_s_provenance(
        trial: Trial,
    ) -> None:
        trial.coding.replies(Judgement(verdict="fix", findings=[_FINDING]))

        transition = trial.walk(judge, Diff(base="main", text=_DIFF, pinned="abc123"))

        assert transition == done(
            Review(base="main", verdict="fix", findings=[_FINDING], pinned="abc123")
        )

    @staticmethod
    def test_the_reviewer_is_read_only_by_permission_not_by_request(
        trial: Trial,
    ) -> None:
        trial.coding.replies(Judgement(verdict="ship", findings=[]))

        trial.walk(judge, Diff(base="main", text=_DIFF))

        options = trial.coding.calls[0].focus_options
        assert options is not None
        assert options.model_dump()["allowed_tools"] == ["Read", "Grep", "Glob"]
        assert options.model_dump()["permission_mode"] == "dontAsk"

    @staticmethod
    def test_a_focus_asked_for_puts_it_in_front_of_the_diff(trial: Trial) -> None:
        trial.coding.replies(Judgement(verdict="ship", findings=[]))

        trial.walk(judge, Diff(base="main", text=_DIFF, focus="the locking"))

        assert "Pay particular attention to: the locking" in trial.coding.prompts[0]


class TestReviewWhole:
    @staticmethod
    def test_a_diff_with_findings_comes_back_as_a_review(trial: Trial) -> None:
        trial.shell.replies(when="git diff main...HEAD", stdout=_DIFF)
        trial.coding.replies(Judgement(verdict="fix", findings=[_FINDING]))

        result = trial.cast(review, ReviewRequest(base="main"))

        assert result == Review(
            base="main", verdict="fix", findings=[_FINDING], pinned=_pinned(_DIFF)
        )
        assert trial.steps == ["collect", "judge"]
