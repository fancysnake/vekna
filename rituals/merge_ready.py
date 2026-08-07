# merge_ready — run both gates at once, and babysit them to green.

import asyncio

from pydantic import BaseModel

from vekna.folio.coding import Session, coding
from vekna.folio.flow import decide
from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import Transition, done, goto, ritual, step

from .prompts import REPAIR
from .shared import Bound


class MergeReady(BaseModel):
    bound: Bound = 3


class Attempt(BaseModel):
    budget: int


class LintFailure(BaseModel):
    budget: int
    lint: str


class SuiteFailure(BaseModel):
    budget: int
    suite: str


class BothRed(BaseModel):
    budget: int
    lint: str
    suite: str


class MergeReport(BaseModel):
    green: bool
    remaining: int


Red = LintFailure | SuiteFailure | BothRed

_HEADLINE = {
    LintFailure: "the linters are red",
    SuiteFailure: "the suite is red",
    BothRed: "the linters and the suite are red",
}


# Both streams, in arrival order as far as two captures allow: mypy and pylint
# put their diagnostics on stdout, but a task that dies before it starts — a
# missing tool, a bad flag, a traceback — says so on stderr and nowhere else.
# Passing stdout alone hands the repair agent an empty complaint.
def _said(result: ShellResult) -> str:
    return "\n".join(part for part in (result.stdout, result.stderr) if part.strip())


def _red(*, budget: int, lint: ShellResult, suite: ShellResult) -> Red:
    if lint.exit_code and suite.exit_code:
        return BothRed(budget=budget, lint=_said(lint), suite=_said(suite))
    if lint.exit_code:
        return LintFailure(budget=budget, lint=_said(lint))
    return SuiteFailure(budget=budget, suite=_said(suite))


def _lint_said(failure: LintFailure | BothRed) -> str:
    return f"The linters said:\n\n{failure.lint}"


def _suite_said(failure: SuiteFailure | BothRed) -> str:
    return f"The suite said:\n\n{failure.suite}"


def _complaint(failure: Red) -> str:
    if isinstance(failure, BothRed):
        return f"{_lint_said(failure)}\n\n{_suite_said(failure)}"
    if isinstance(failure, LintFailure):
        return _lint_said(failure)
    return _suite_said(failure)


# max_steps is the backstop, not the control — the bound is. It sits well above
# a plausible bound, so tripping it means a ritual that will not settle.
@ritual("merge_ready", max_steps=32)
def merge_ready(components: MergeReady) -> Transition:
    return goto(gates, Attempt(budget=components.bound))


@step
async def gates(state: Attempt) -> Transition:
    # Both gates take minutes, and neither reads the other's output. Running
    # them at once is not only faster: one cast then tells you everything that
    # is red, rather than the first thing that is red.
    async with asyncio.TaskGroup() as group:
        linting = group.create_task(shell("mise run lint:py"))
        suite = group.create_task(shell("mise run test:py"))
    lint, tests = linting.result(), suite.result()
    if not lint.exit_code and not tests.exit_code:
        return done(MergeReport(green=True, remaining=state.budget))
    if state.budget <= 0:
        return done(MergeReport(green=False, remaining=0))
    failure = _red(budget=state.budget, lint=lint, suite=tests)
    # The agent's time is yours to spend, so the decision to spend it is a step
    # boundary, not something the agent decides for itself.
    attempts = "attempt" if state.budget == 1 else "attempts"
    spend = await decide(
        f"{_HEADLINE[type(failure)]}, {state.budget} {attempts} left"
        " — hand it to the agent?"
    )
    if not spend:
        return done(MergeReport(green=False, remaining=state.budget))
    return goto(repair, failure)


# Three payload shapes, one step: whichever gate went red, this is where it is
# repaired, and the prompt says only what actually failed.
# The loop is what the thread is for. Every pass through here meets a failure
# the previous pass tried and failed to fix, and an agent starting fresh each
# time will reach for the same idea again. A key rather than a bare `continue`:
# they are the same thing in a ritual whose only agent call this is, and they
# stop being the same the moment a second one is added.
@step
async def repair(failure: Red) -> Transition:
    await coding(REPAIR + _complaint(failure), session=Session.CONTINUE, key="repair")
    return goto(gates, Attempt(budget=failure.budget - 1))
