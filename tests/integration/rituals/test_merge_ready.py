import pytest

from rituals.merge_ready import (
    Attempt,
    BothRed,
    LintFailure,
    MergeReady,
    MergeReport,
    SuiteFailure,
    gates,
    merge_ready,
    repair,
)
from vekna.lexicon import StepBudgetExceededError, done, goto
from vekna.trial import Trial

_LINT = "mise run lint:py"
_SUITE = "mise run test:py"
_SPEND = "*hand it to the agent?*"


class TestGates:
    @staticmethod
    def test_both_green_ends_the_ritual_with_the_budget_untouched(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=0)
        trial.shell.replies(when=_SUITE, exit_code=0)

        transition = trial.walk(gates, Attempt(budget=3))

        assert transition == done(MergeReport(green=True, remaining=3))
        assert sorted(trial.shell.commands) == [_LINT, _SUITE]

    # Which of the two lands first is the scheduler's business, so the payload
    # has to come from the command and not from arrival. Once is enough to say
    # so here; what makes it true is `Script` preferring a pattern over the
    # queue, and tests/unit/trial/test_script.py fails deterministically if that
    # stops holding.
    @staticmethod
    def test_the_red_gate_is_named_by_its_command_not_by_which_landed_first(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=0)
        trial.decide.answers(answer=True, when=_SPEND)

        transition = trial.walk(gates, Attempt(budget=1))

        assert transition == goto(repair, LintFailure(budget=1, lint="E501"))

    @staticmethod
    def test_a_red_suite_alone_picks_the_suite_payload(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=0)
        trial.shell.replies(when=_SUITE, exit_code=1, stdout="1 failed")
        trial.decide.answers(answer=True, when=_SPEND)

        transition = trial.walk(gates, Attempt(budget=2))

        assert transition == goto(repair, SuiteFailure(budget=2, suite="1 failed"))

    @staticmethod
    def test_both_red_carries_both_complaints(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=1, stdout="1 failed")
        trial.decide.answers(answer=True, when=_SPEND)

        transition = trial.walk(gates, Attempt(budget=2))

        assert transition == goto(
            repair, BothRed(budget=2, lint="E501", suite="1 failed")
        )

    # A task that dies before it starts says so on stderr and nowhere else.
    # Passing stdout alone hands the repair agent an empty complaint.
    @staticmethod
    def test_a_gate_that_died_before_it_ran_still_reaches_the_agent(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when=_LINT, exit_code=127, stderr="mise: no such task\n")
        trial.shell.replies(when=_SUITE, exit_code=0)
        trial.decide.answers(answer=True, when=_SPEND)

        transition = trial.walk(gates, Attempt(budget=1))

        assert transition == goto(
            repair, LintFailure(budget=1, lint="mise: no such task\n")
        )

    @staticmethod
    def test_the_prompt_names_what_is_red_and_what_is_left(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=1, stdout="1 failed")
        trial.decide.answers(answer=False)

        trial.walk(gates, Attempt(budget=1))

        asked = "the linters and the suite are red, 1 attempt left"
        assert trial.decide.prompts == [f"{asked} — hand it to the agent?"]

    @staticmethod
    def test_more_than_one_attempt_left_is_said_in_the_plural(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=0)
        trial.decide.answers(answer=False)

        trial.walk(gates, Attempt(budget=2))

        assert "the linters are red, 2 attempts left" in trial.decide.prompts[0]

    @staticmethod
    def test_declining_ends_the_ritual_with_the_budget_unspent(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=0)
        trial.decide.answers(answer=False, when=_SPEND)

        transition = trial.walk(gates, Attempt(budget=2))

        assert transition == done(MergeReport(green=False, remaining=2))

    @staticmethod
    def test_a_spent_budget_never_asks_at_all(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=0)

        transition = trial.walk(gates, Attempt(budget=0))

        assert transition == done(MergeReport(green=False, remaining=0))
        assert not trial.decide.asked


class TestRepair:
    @staticmethod
    def test_only_what_actually_failed_reaches_the_agent(trial: Trial) -> None:
        trial.coding.replies("fixed the long line")

        transition = trial.walk(repair, LintFailure(budget=2, lint="E501"))

        assert transition == goto(gates, Attempt(budget=1))
        assert "The linters said:\n\nE501" in trial.coding.prompts[0]
        assert "The suite said" not in trial.coding.prompts[0]

    @staticmethod
    def test_both_complaints_are_carried_when_both_gates_went_red(trial: Trial) -> None:
        trial.coding.replies("fixed both")

        trial.walk(repair, BothRed(budget=1, lint="E501", suite="1 failed"))

        assert "The linters said:\n\nE501" in trial.coding.prompts[0]
        assert "The suite said:\n\n1 failed" in trial.coding.prompts[0]

    @staticmethod
    def test_a_red_suite_alone_says_only_that(trial: Trial) -> None:
        trial.coding.replies("fixed it")

        trial.walk(repair, SuiteFailure(budget=1, suite="1 failed"))

        assert "The suite said:\n\n1 failed" in trial.coding.prompts[0]
        assert "The linters said" not in trial.coding.prompts[0]


class TestMergeReadyWhole:
    # The path the ritual exists for: red, repaired once, green.
    @staticmethod
    def test_it_repairs_once_and_then_goes_green(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501")
        trial.shell.replies(when=_SUITE, exit_code=0, always=True)
        trial.shell.replies(when=_LINT, exit_code=0)
        trial.decide.answers(answer=True, when=_SPEND)
        trial.coding.replies("fixed the long line")

        result = trial.cast(merge_ready, MergeReady(bound=2))

        assert result == MergeReport(green=True, remaining=1)
        assert trial.steps == ["gates", "repair", "gates"]
        assert "E501" in trial.coding.prompts[0]

    # Every pass meets a failure the previous pass tried and failed to fix, so
    # the second call joins the first one's thread rather than starting fresh.
    @staticmethod
    def test_each_repair_carries_on_from_the_one_before_it(trial: Trial) -> None:
        trial.shell.replies(when=_LINT, exit_code=1, stdout="E501", always=True)
        trial.shell.replies(when=_SUITE, exit_code=0, always=True)
        trial.decide.answers(answer=True, when=_SPEND, always=True)
        trial.coding.replies("tried", always=True)

        result = trial.cast(merge_ready, MergeReady(bound=2))

        assert result == MergeReport(green=False, remaining=0)
        assert trial.coding.calls[0].resume is None
        assert trial.coding.calls[1].resume == "s1"

    @staticmethod
    def test_a_ritual_that_will_not_settle_trips_max_steps(trial: Trial) -> None:
        trial.shell.replies(when="*", exit_code=1, stdout="red", always=True)
        trial.decide.answers(answer=True, when=_SPEND, always=True)
        trial.coding.replies("tried", always=True)

        # 32 steps at a bound the budget never reaches: the backstop, not the
        # control.
        with pytest.raises(StepBudgetExceededError, match="exceeded max_steps=32"):
            trial.cast(merge_ready, MergeReady(bound=64))
