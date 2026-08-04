import asyncio

import pytest
from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, CodingOutputError, Session, coding
from vekna.folio.flow import decide
from vekna.folio.shell import shell
from vekna.lexicon import (
    StepBoundaryError,
    Transition,
    done,
    focus_scope,
    goto,
    resolve_focus,
    ritual,
    step,
)
from vekna.trial import Trial, TrialError, TrialScriptError

# The whole shape a ritual has, in four steps: a shell gate, an agent behind a
# decide, a threaded retry, and a typed answer read off a schema.


class Attempt(BaseModel):
    budget: int


class Failure(BaseModel):
    budget: int
    said: str


class Report(BaseModel):
    green: bool
    remaining: int


class Judgement(BaseModel):
    verdict: str


@step
async def gates(state: Attempt) -> Transition:
    async with asyncio.TaskGroup() as group:
        linting = group.create_task(shell("mise run lint:py"))
        suite = group.create_task(shell("mise run test:py"))
    lint, tests = linting.result(), suite.result()
    if not lint.exit_code and not tests.exit_code:
        return done(Report(green=True, remaining=state.budget))
    if state.budget <= 0:
        return done(Report(green=False, remaining=0))
    if not await decide("red — hand it to the agent?"):
        return done(Report(green=False, remaining=state.budget))
    return goto(repair, Failure(budget=state.budget, said=lint.stdout + tests.stdout))


@step
async def repair(failure: Failure) -> Transition:
    await coding(
        f"make it green: {failure.said}", session=Session.CONTINUE, key="repair"
    )
    return goto(gates, Attempt(budget=failure.budget - 1))


@step
async def one_gate(_state: Attempt) -> Transition:
    return done(await shell("mise run test:py"))


@step
async def judge(_state: Attempt) -> Transition:
    return done(await coding("review the diff", output=Judgement))


@step
async def gated_work(_state: Attempt) -> Transition:
    await coding("write the tests", opts=CodingOpts(gate_tools=["Bash"]))
    return done()


@ritual("babysit", max_steps=32)
def babysit(components: Attempt) -> Transition:
    return goto(gates, components)


class TestCast:
    @staticmethod
    def test_a_red_gate_repairs_once_and_then_goes_green(trial: Trial) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=1, stdout="E501")
        trial.shell.replies(when="mise run test:py", exit_code=0, always=True)
        trial.shell.replies(when="mise run lint:py", exit_code=0)
        trial.decide.answers(answer=True, when="*hand it to the agent?*")
        trial.coding.replies("fixed the long line")

        result = trial.cast(babysit, Attempt(budget=2))

        assert result == Report(green=True, remaining=1)
        assert trial.steps == ["gates", "repair", "gates"]
        assert "E501" in trial.coding.prompts[0]

    @staticmethod
    def test_concurrent_gates_are_answered_by_pattern_not_by_arrival(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=0, always=True)
        trial.shell.replies(when="mise run test:py", exit_code=1, always=True)

        result = trial.cast(babysit, Attempt(budget=0))

        assert result == Report(green=False, remaining=0)

    @staticmethod
    def test_the_human_declining_ends_the_cast_there(trial: Trial) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=1, always=True)
        trial.shell.replies(when="mise run test:py", exit_code=0, always=True)
        trial.decide.answers(answer=False)

        result = trial.cast(babysit, Attempt(budget=2))

        assert result == Report(green=False, remaining=2)
        assert trial.steps == ["gates"]
        assert not trial.coding.calls

    @staticmethod
    def test_a_threaded_retry_resumes_the_first_call_s_session(trial: Trial) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=1)
        trial.shell.replies(when="mise run test:py", exit_code=0, always=True)
        trial.shell.replies(when="mise run lint:py", exit_code=1)
        trial.shell.replies(when="mise run lint:py", exit_code=0)
        trial.decide.answers(answer=True, when="*agent?*", always=True)
        trial.coding.replies("tried once", always=True)

        trial.cast(babysit, Attempt(budget=2))

        assert trial.coding.calls[0].resume is None
        assert trial.coding.calls[1].resume == "s1"

    @staticmethod
    def test_what_the_mediums_streamed_is_kept_alongside_the_rites(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=1, stdout="E501\n")
        trial.shell.replies(when="mise run test:py", exit_code=0, always=True)
        trial.shell.replies(when="mise run lint:py", exit_code=0)
        trial.decide.answers(answer=True, when="*agent?*")
        trial.coding.replies("fixed it")

        trial.cast(babysit, Attempt(budget=1))

        assert trial.deltas == ["E501", "fixed it"]
        assert [type(event).__name__ for event in trial.events[:2]] == [
            "RiteBegan",
            "RiteBegan",
        ]

    @staticmethod
    def test_no_subprocess_is_started_and_no_stdin_is_read(trial: Trial) -> None:
        trial.shell.replies(when="*", exit_code=0, always=True)

        trial.cast(babysit, Attempt(budget=1))

        assert trial.shell.commands == ["mise run lint:py", "mise run test:py"]
        assert not trial.decide.asked


class TestWalk:
    @staticmethod
    def test_one_step_answers_with_its_transition_and_no_ritual(trial: Trial) -> None:
        trial.shell.replies(when="*", exit_code=0, always=True)

        transition = trial.walk(gates, Attempt(budget=3))

        assert transition == done(Report(green=True, remaining=3))
        assert trial.shell.commands == ["mise run lint:py", "mise run test:py"]

    @staticmethod
    def test_the_step_that_ran_is_recorded_the_way_a_cast_records_it(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="*", exit_code=0, always=True)

        trial.walk(gates, Attempt(budget=1))

        assert trial.steps == ["gates"]

    @staticmethod
    def test_a_payload_of_the_wrong_type_is_refused_the_way_a_cast_refuses_it(
        trial: Trial,
    ) -> None:
        with pytest.raises(StepBoundaryError, match=r"expected .*Attempt"):
            trial.walk(gates, Failure(budget=1, said="nope"))


class TestScriptedOutput:
    @staticmethod
    def test_a_scripted_model_comes_back_validated_by_the_medium(trial: Trial) -> None:
        trial.coding.replies(Judgement(verdict="ship"))

        transition = trial.walk(judge, Attempt(budget=0))

        assert transition == done(Judgement(verdict="ship"))

    @staticmethod
    def test_a_reply_that_does_not_validate_raises_the_medium_s_own_error(
        trial: Trial,
    ) -> None:
        trial.coding.replies("not json at all")

        with pytest.raises(CodingOutputError, match="does not validate"):
            trial.walk(judge, Attempt(budget=0))


class TestGatedTools:
    @staticmethod
    def test_a_tool_the_agent_reaches_for_is_put_to_the_human(trial: Trial) -> None:
        trial.coding.replies("ran the suite", uses=["Bash"])
        trial.decide.answers(answer=True, when="*allow tool*")

        trial.walk(gated_work, Attempt(budget=0))

        assert trial.coding.gated == [("Bash", True)]
        assert trial.decide.prompts == ["allow tool 'Bash'?"]

    @staticmethod
    def test_a_refused_tool_comes_back_refused(trial: Trial) -> None:
        trial.coding.replies("asked and was told no", uses=["Bash"])
        trial.decide.answers(answer=False, when="*allow tool*")

        trial.walk(gated_work, Attempt(budget=0))

        assert trial.coding.gated == [("Bash", False)]


class TestNothingDefaults:
    @staticmethod
    def test_an_unscripted_command_stops_the_step_naming_itself(trial: Trial) -> None:
        with pytest.raises(TrialScriptError, match="'mise run test:py'"):
            trial.walk(one_gate, Attempt(budget=0))

    # Inside a TaskGroup it arrives wrapped, the way any error raised in one
    # does. That is Python's, not the trial's — and worth a test, because it is
    # what an author will actually see.
    @staticmethod
    def test_an_unscripted_command_in_a_task_group_still_stops_the_cast(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="mise run lint:py", exit_code=0)

        with pytest.raises(BaseExceptionGroup) as raised:
            trial.cast(babysit, Attempt(budget=1))

        assert isinstance(raised.value.exceptions[0], TrialScriptError)
        assert "'mise run test:py'" in str(raised.value.exceptions[0])

    @staticmethod
    def test_an_answer_outside_the_options_never_reaches_the_ritual(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="*", exit_code=1, always=True)
        trial.decide.answers(answer="repair")

        with pytest.raises(TrialScriptError, match="not one of the offered answers"):
            trial.cast(babysit, Attempt(budget=1))


class TestTheLoop:
    @staticmethod
    def test_cast_from_inside_a_running_loop_says_which_call_to_use(
        trial: Trial,
    ) -> None:
        async def inside() -> None:
            await asyncio.sleep(0)
            trial.cast(babysit, Attempt(budget=0))

        with pytest.raises(TrialError, match="call cast_async"):
            asyncio.run(inside())

    @staticmethod
    def test_walk_from_inside_a_running_loop_says_which_call_to_use(
        trial: Trial,
    ) -> None:
        async def inside() -> None:
            await asyncio.sleep(0)
            trial.walk(gates, Attempt(budget=0))

        with pytest.raises(TrialError, match="call walk_async"):
            asyncio.run(inside())

    @staticmethod
    def test_the_async_pair_runs_inside_a_loop_the_suite_already_owns(
        trial: Trial,
    ) -> None:
        trial.shell.replies(when="*", exit_code=0, always=True)

        result = asyncio.run(trial.cast_async(babysit, Attempt(budget=1)))

        assert result == Report(green=True, remaining=1)


class TestRegistryIsLeftAsFound:
    @staticmethod
    def test_a_focus_registered_before_the_trial_comes_back_after_it() -> None:
        # The outer scope is the test's own tidying, not part of what is
        # asserted: the registry is global, and a focus left behind here would
        # answer for whatever ran next.
        with focus_scope("shell", "the author's own"):
            with Trial():
                pass

            assert resolve_focus("shell") == "the author's own"

    # What `shell()` resolves to once the double is gone is bash, which
    # tests/integration/folio/test_shell.py is where it is proven.
    @staticmethod
    def test_a_medium_nothing_installed_is_uninstalled_again() -> None:
        with Trial():
            pass

        assert resolve_focus("shell", default="bash again") == "bash again"
