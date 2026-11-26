import pytest
from pydantic import ValidationError

from rituals.cover_diff import (
    CoverDiff,
    CoverReport,
    Uncovered,
    WriteTests,
    cover_diff,
    measure,
    write_tests,
)
from vekna.lexicon import Done
from vekna.trial import Trial

_GATE = "mise run test:py:cov:diff -- --fail-under 100"
_UNCOVERED = "src/vekna/thing.py (80%): Missing lines 12,13"
_LARGEST_BOUND = 15


class TestMeasure:
    @staticmethod
    def test_a_green_gate_ends_the_ritual_with_the_budget_untouched(
        trial: Trial,
    ) -> None:
        # The glob form, because it is the one the ritual-scribe skill teaches.
        trial.shell.replies(when="mise run test:py:cov:diff*", exit_code=0)

        transition = trial.walk(measure, Uncovered(budget=3))

        assert transition == Done(CoverReport(covered=True, remaining=3))
        assert trial.shell.commands == [_GATE]

    @staticmethod
    def test_a_red_gate_hands_the_report_to_the_agent(trial: Trial) -> None:
        trial.shell.replies(when=_GATE, exit_code=1, stdout=_UNCOVERED)

        transition = trial.walk(measure, Uncovered(budget=2))

        assert transition == WriteTests(budget=2, report=_UNCOVERED)

    @staticmethod
    def test_a_spent_budget_ends_red_rather_than_asking_again(trial: Trial) -> None:
        trial.shell.replies(when=_GATE, exit_code=1, stdout=_UNCOVERED)

        transition = trial.walk(measure, Uncovered(budget=0))

        # The report rides out with the failure: a cast that gave up still says
        # which lines it gave up on.
        assert transition == Done(
            CoverReport(covered=False, remaining=0, report=_UNCOVERED)
        )


class TestWriteTests:
    @staticmethod
    def test_the_report_reaches_the_agent_and_the_budget_comes_down(
        trial: Trial,
    ) -> None:
        trial.coding.replies("wrote a test")

        transition = trial.walk(write_tests, WriteTests(budget=2, report=_UNCOVERED))

        assert transition == Uncovered(budget=1)
        assert _UNCOVERED in trial.coding.prompts[0]
        assert "diff-cover reports lines this branch changed" in trial.coding.prompts[0]

    # The one thing this step is arranged to prevent: an agent whose brief is
    # "make the coverage number go up" running commands unwatched.
    @staticmethod
    def test_every_command_the_agent_reaches_for_is_put_to_the_human(
        trial: Trial,
    ) -> None:
        trial.coding.replies("ran the suite", uses=["Bash"])
        trial.decide.answers(answer=False, when="*allow tool*")

        trial.walk(write_tests, WriteTests(budget=1, report=""))

        assert trial.coding.gated == [("Bash", False)]
        assert trial.decide.prompts == ["allow tool 'Bash'?"]


class TestCoverDiffWhole:
    @staticmethod
    def test_it_writes_a_test_and_then_measures_green(trial: Trial) -> None:
        trial.shell.replies(when=_GATE, exit_code=1, stdout=_UNCOVERED)
        trial.shell.replies(when=_GATE, exit_code=0)
        trial.coding.replies("wrote a test")

        result = trial.cast(cover_diff, CoverDiff(bound=3))

        assert result == CoverReport(covered=True, remaining=2)
        assert trial.steps == ["measure", "write_tests", "measure"]

    @staticmethod
    def test_a_gate_that_stays_red_gives_up_when_the_bound_runs_out(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when=_GATE, exit_code=1, stdout=_UNCOVERED, always=True)
        trial.coding.replies("tried", always=True)

        result = trial.cast(cover_diff, CoverDiff(bound=1))

        assert result == CoverReport(covered=False, remaining=0, report=_UNCOVERED)
        assert trial.steps == ["measure", "write_tests", "measure"]

    @staticmethod
    def test_the_largest_bound_the_step_cap_holds_still_reports(trial: Trial) -> None:
        trial.shell.replies(when=_GATE, exit_code=1, stdout=_UNCOVERED, always=True)
        trial.coding.replies("tried", always=True)

        result = trial.cast(cover_diff, CoverDiff(bound=_LARGEST_BOUND))

        assert result == CoverReport(covered=False, remaining=0, report=_UNCOVERED)
        assert len(trial.steps) == 2 * _LARGEST_BOUND + 1
        assert trial.shell.commands == [_GATE] * (_LARGEST_BOUND + 1)
        assert len(trial.coding.prompts) == _LARGEST_BOUND

    @staticmethod
    def test_a_bound_past_the_step_cap_is_refused() -> None:
        with pytest.raises(ValidationError, match="less than or equal to 15"):
            CoverDiff(bound=16)
