import pytest

from rituals.sweep import (
    CiFix,
    CiWatch,
    Fixed,
    Listing,
    Queued,
    Swept,
    Watched,
    ci_watch,
    fan_out,
    pr_fix,
)
from vekna.lexicon import Done, RitualError
from vekna.trial import Trial

_LIST = "gh pr list --base main --limit 10 --json number --jq '.[].number'"
_CHECKS = "gh pr checks 7 --watch"
_CHECKOUT = "gh pr checkout 7"
_DIFF = "git diff --end-of-options main...HEAD"
_AHEAD = "git log --oneline @{upstream}..HEAD"
_PUSH = "git push --end-of-options origin HEAD"
_PUSH_IT = "push the fix to #7?"


class TestSweep:
    @staticmethod
    def test_queues_one_watch_per_pull_request(trial: Trial) -> None:
        trial.shell.replies(when="gh pr list *", exit_code=0, stdout="7\n9\n")

        transition = trial.walk(fan_out, Listing(base_branch="main", max_prs=10))

        assert transition == Done(
            Swept(
                queued=[
                    Queued(pull_request=7, cast_id="c1"),
                    Queued(pull_request=9, cast_id="c2"),
                ]
            )
        )
        assert trial.shell.commands == [_LIST]
        assert [cast.components for cast in trial.queue.enqueued] == [
            CiWatch(pull_request=7, base_branch="main"),
            CiWatch(pull_request=9, base_branch="main"),
        ]
        assert trial.queue.rituals == ["ci_watch", "ci_watch"]

    @staticmethod
    def test_a_failed_listing_queues_nothing(trial: Trial) -> None:
        trial.shell.replies(when="gh pr list *", exit_code=1, stderr="not a repo")

        with pytest.raises(RitualError, match="not a repo"):
            trial.walk(fan_out, Listing(base_branch="main", max_prs=10))

        assert trial.queue.enqueued == []


class TestCiWatch:
    @staticmethod
    def test_green_checks_need_no_fix(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=0)

        result = trial.cast(ci_watch, CiWatch(pull_request=7, base_branch="main"))

        assert result == Watched(pull_request=7, green=True, why="green")
        assert trial.queue.enqueued == []

    @staticmethod
    def test_red_checks_wait_on_a_fix_then_watch_again(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.shell.replies(when=_CHECKS, exit_code=0)
        trial.queue.returns(Fixed(pushed=True), when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7, base_branch="main"))

        assert result == Watched(pull_request=7, green=True, why="green")
        assert trial.steps == ["watch", "fix", "watch"]
        (child,) = trial.queue.enqueued
        assert child.components == CiFix(
            pull_request=7, checks="lint fail", base_branch="main"
        )
        # Unset, so the child's repository answers it from `[defaults.pr_fix]`.
        assert "remote" not in child.components.model_fields_set

    @staticmethod
    def test_red_with_no_fixes_left_gives_up(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")

        result = trial.cast(
            ci_watch, CiWatch(pull_request=7, base_branch="main", fixes=0)
        )

        assert result == Watched(pull_request=7, green=False, why="out of fixes")
        assert trial.queue.enqueued == []

    @staticmethod
    def test_a_fix_not_pushed_ends_red(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.queue.returns(Fixed(pushed=False), when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7, base_branch="main"))

        assert result == Watched(pull_request=7, green=False, why="fix not pushed")

    @staticmethod
    def test_a_failed_fix_cast_is_the_verdict(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.queue.fails("no tree", when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7, base_branch="main"))

        assert result == Watched(
            pull_request=7, green=False, why="cast c1 ended error: no tree"
        )
        assert trial.steps == ["watch", "fix", "fix_failed"]

    @staticmethod
    def test_gh_failing_is_not_read_as_red(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=4, stderr="auth required")

        result = trial.cast(ci_watch, CiWatch(pull_request=7, base_branch="main"))

        assert result.green is False
        assert "auth required" in result.why
        assert trial.steps == ["watch", "gave_up"]


def _fixing(trial: Trial, *, committed: str) -> None:
    trial.shell.replies(when=_CHECKOUT, exit_code=0)
    trial.shell.replies(when=_DIFF, exit_code=0, stdout="+bad line")
    trial.coding.replies("fixed the lint")
    trial.shell.replies(when=_AHEAD, exit_code=0, stdout=committed)


_PR_FIX = CiFix(pull_request=7, checks="lint fail", base_branch="main")


class TestPrFix:
    @staticmethod
    def test_a_committed_fix_is_pushed_once_agreed(trial: Trial) -> None:
        _fixing(trial, committed="abc123 fix lint\n")
        trial.decide.answers(answer=True, when=_PUSH_IT)
        trial.shell.replies(when=_PUSH, exit_code=0)

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(pushed=True)
        assert trial.shell.commands == [_CHECKOUT, _DIFF, _AHEAD, _PUSH]
        assert "lint fail" in trial.coding.prompts[0]
        assert "+bad line" in trial.coding.prompts[0]

    @staticmethod
    def test_nothing_committed_asks_nothing(trial: Trial) -> None:
        _fixing(trial, committed="")

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(pushed=False)
        assert trial.decide.prompts == []

    @staticmethod
    def test_a_declined_push_pushes_nothing(trial: Trial) -> None:
        _fixing(trial, committed="abc123 fix lint\n")
        trial.decide.answers(answer=False, when=_PUSH_IT)

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(pushed=False)
        assert _PUSH not in trial.shell.commands
