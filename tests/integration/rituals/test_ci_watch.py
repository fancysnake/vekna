from rituals.ci_watch import CiWatch, Watched, ci_watch
from rituals.pr_fix import CiFix, Fixed
from vekna.trial import Trial

_CHECKS = "gh pr checks 7 --watch"


class TestCiWatch:
    @staticmethod
    def test_green_checks_need_no_fix(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=0)

        result = trial.cast(ci_watch, CiWatch(pull_request=7))

        assert result == Watched(pull_request=7, outcome="green")
        assert trial.queue.enqueued == []

    @staticmethod
    def test_red_checks_wait_on_a_fix_then_watch_again(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.shell.replies(when=_CHECKS, exit_code=0)
        trial.queue.returns(Fixed(outcome="pushed"), when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7))

        assert result == Watched(pull_request=7, outcome="green")
        assert trial.steps == ["watch", "watch"]
        (child,) = trial.queue.enqueued
        assert child.components == CiFix(pull_request=7, checks="lint fail")
        # Unset, so the child's repository answers it from `[defaults.pr_fix]`.
        assert "remote" not in child.components.model_fields_set

    @staticmethod
    def test_red_with_no_fixes_left_gives_up(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")

        result = trial.cast(ci_watch, CiWatch(pull_request=7, fixes=0))

        assert result == Watched(pull_request=7, outcome="out of fixes")
        assert trial.queue.enqueued == []

    @staticmethod
    def test_a_fix_not_pushed_ends_red_saying_why(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.queue.returns(Fixed(outcome="declined"), when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7))

        assert result == Watched(
            pull_request=7, outcome="fix not pushed", detail="declined"
        )

    @staticmethod
    def test_a_failed_fix_cast_is_the_verdict(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=1, stdout="lint fail")
        trial.queue.fails("no tree", when="pr_fix")

        result = trial.cast(ci_watch, CiWatch(pull_request=7))

        assert result == Watched(
            pull_request=7, outcome="failed", detail="cast c1 ended error: no tree"
        )
        assert trial.steps == ["watch", "gave_up"]

    @staticmethod
    def test_gh_failing_is_not_read_as_red(trial: Trial) -> None:
        trial.shell.replies(when=_CHECKS, exit_code=4, stderr="auth required")

        result = trial.cast(ci_watch, CiWatch(pull_request=7))

        assert result.outcome == "failed"
        assert "auth required" in result.detail
        assert trial.steps == ["watch", "gave_up"]
