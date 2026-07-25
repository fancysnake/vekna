"""Worked examples for ``vekna cast`` (standalone, no daemon).

Run them from this directory:

    vekna cast fix_demo --bound 3
    vekna cast cover_diff --bound 3

``fix_demo`` is a guarded fix loop: it checks whether the work is done
(``shell``), and while it isn't, asks you whether to apply a fix (``decide``)
and loops back until the check passes or the attempt budget runs out.

``cover_diff`` is the same loop with a coding agent doing the work: measure
this branch's diff coverage (``shell``), hand the uncovered lines to Claude
(``coding``), measure again. The agent runs permissively inside its step —
it edits files and runs commands without asking — while the decision to keep
going stays at the step boundary, where ``diff-cover`` either passes or the
attempt budget runs out. That is the whole bargain: agents are non-deterministic
inside a step, deterministic between them.
"""

from pydantic import BaseModel

from vekna.folio.coding import coding
from vekna.folio.flow import decide
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step


class Attempt(BaseModel):
    budget: int


class Report(BaseModel):
    fixed: bool
    remaining: int


@ritual("fix_demo")
async def fix_demo(bound: int) -> Transition:
    # The entrypoint: map the CLI Component into the first step's payload.
    return goto(check, Attempt(budget=bound))


@step
async def check(attempt: Attempt) -> Transition:
    result = await shell("test -f .fixed")
    if result.exit_code == 0:
        return done(Report(fixed=True, remaining=attempt.budget))
    if attempt.budget == 0:
        return done(Report(fixed=False, remaining=0))
    choice = await decide(
        f"not fixed yet ({attempt.budget} attempts left) — apply a fix?",
        options=["fix", "stop"],
    )
    if choice == "stop":
        return done(Report(fixed=False, remaining=attempt.budget))
    return goto(apply_fix, attempt)


@step
async def apply_fix(attempt: Attempt) -> Transition:
    await shell("touch .fixed")
    return goto(check, Attempt(budget=attempt.budget - 1))


class Uncovered(BaseModel):
    budget: int
    report: str = ""


class CoverReport(BaseModel):
    covered: bool
    remaining: int


@ritual("cover_diff")
async def cover_diff(bound: int) -> Transition:
    return goto(measure, Uncovered(budget=bound))


@step
async def measure(state: Uncovered) -> Transition:
    # `mise run diff-cover` runs the suite under coverage, then fails when the
    # lines this branch changed are not exercised by a test.
    result = await shell("mise run diff-cover")
    if result.exit_code == 0:
        return done(CoverReport(covered=True, remaining=state.budget))
    if state.budget == 0:
        return done(CoverReport(covered=False, remaining=0))
    return goto(write_tests, Uncovered(budget=state.budget, report=result.stdout))


@step
async def write_tests(state: Uncovered) -> Transition:
    # The report names the uncovered lines, so the agent gets the failure
    # rather than a description of it.
    await coding(
        "diff-cover reports lines this branch changed that no test exercises. "
        "Write tests that cover them. Do not lower the coverage threshold, "
        "edit the coverage configuration, or delete the offending code.\n\n"
        f"{state.report}"
    )
    return goto(measure, Uncovered(budget=state.budget - 1))
