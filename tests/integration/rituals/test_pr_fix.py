import pytest

from rituals.pr_fix import _FIX_OPTS, CiFix, Fixed, pr_fix
from vekna.lexicon import RitualError
from vekna.trial import Trial

_FORK = "gh pr view 7 --json isCrossRepository --jq .isCrossRepository"
_CHECKOUT = "gh pr checkout 7"
_DIFF = "gh pr diff 7"
_AHEAD = "git log --oneline @{upstream}..HEAD"
_PUSH = "git push --end-of-options origin HEAD"
_PUSH_IT = "push the fix to #7?"


def _fixing(trial: Trial, *, committed: str) -> None:
    trial.shell.replies(when=_FORK, exit_code=0, stdout="false\n")
    trial.shell.replies(when=_CHECKOUT, exit_code=0)
    trial.shell.replies(when=_DIFF, exit_code=0, stdout="+bad line")
    trial.coding.replies("fixed the lint")
    trial.shell.replies(when=_AHEAD, exit_code=0, stdout=committed)


_PR_FIX = CiFix(pull_request=7, checks="lint fail")


class TestPrFix:
    @staticmethod
    def test_a_committed_fix_is_pushed_once_agreed(trial: Trial) -> None:
        _fixing(trial, committed="abc123 fix lint\n")
        trial.decide.answers(answer=True, when=_PUSH_IT)
        trial.shell.replies(when=_PUSH, exit_code=0)

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(outcome="pushed")
        assert trial.shell.commands == [_FORK, _CHECKOUT, _DIFF, _AHEAD, _PUSH]
        assert "lint fail" in trial.coding.prompts[0]
        assert "+bad line" in trial.coding.prompts[0]
        assert trial.coding.calls[0].focus_options == _FIX_OPTS.focus_options

    @staticmethod
    def test_a_fork_is_refused_before_checkout(trial: Trial) -> None:
        trial.shell.replies(when=_FORK, exit_code=0, stdout="true\n")

        with pytest.raises(RitualError, match="#7 is from a fork"):
            trial.cast(pr_fix, _PR_FIX)

        assert trial.shell.commands == [_FORK]
        assert trial.coding.prompts == []

    @staticmethod
    def test_nothing_committed_asks_nothing(trial: Trial) -> None:
        _fixing(trial, committed="")

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(outcome="nothing committed")
        assert trial.decide.prompts == []

    @staticmethod
    def test_a_declined_push_pushes_nothing(trial: Trial) -> None:
        _fixing(trial, committed="abc123 fix lint\n")
        trial.decide.answers(answer=False, when=_PUSH_IT)

        result = trial.cast(pr_fix, _PR_FIX)

        assert result == Fixed(outcome="declined")
        assert _PUSH not in trial.shell.commands

    @staticmethod
    @pytest.mark.parametrize(
        ("failing", "said"),
        [
            (_FORK, "reading where #7 comes from failed"),
            (_CHECKOUT, "checking out #7 failed"),
            (_DIFF, "reading the diff of #7 failed"),
            (_AHEAD, "reading what the fix committed failed"),
        ],
    )
    def test_a_failing_git_step_names_itself(
        trial: Trial, failing: str, said: str
    ) -> None:
        for command in (_FORK, _CHECKOUT, _DIFF, _AHEAD):
            trial.shell.replies(
                when=command, exit_code=int(command == failing), stdout="false\n"
            )
        trial.coding.replies("fixed the lint")

        with pytest.raises(RitualError, match=said):
            trial.cast(pr_fix, _PR_FIX)

    @staticmethod
    def test_a_failed_push_says_so(trial: Trial) -> None:
        _fixing(trial, committed="abc123 fix lint\n")
        trial.decide.answers(answer=True, when=_PUSH_IT)
        trial.shell.replies(when=_PUSH, exit_code=1, stderr="rejected")

        with pytest.raises(RitualError, match="pushing the fix to #7 failed"):
            trial.cast(pr_fix, _PR_FIX)
