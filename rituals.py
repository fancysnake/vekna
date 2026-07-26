"""Vekna's own rituals — this project casts them on itself.

    vekna cast cover_diff

``cover_diff`` closes the coverage gap on the current branch: measure diff
coverage (``shell``), hand the uncovered lines to Claude (``coding``), measure
again. The agent works permissively inside its step — it edits files and runs
commands without asking permission — but it can put a question to you mid-step
through ``ask_human``, which every ``coding`` call offers. The decision to keep
going stays at the step boundary, where ``diff-cover`` either passes or the
attempt budget runs out. That is the whole bargain: agents are
non-deterministic inside a step, deterministic between them.
"""

import asyncio
from typing import Literal

from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, coding
from vekna.folio.coding_claude import ClaudeOptions
from vekna.folio.flow import decide
from vekna.folio.shell import ShellResult, shell
from vekna.lexicon import (
    File,
    GitRef,
    RitualError,
    Text,
    Transition,
    done,
    goto,
    ritual,
    sha256_of,
    step,
)


# cover_diff — close the coverage gap on this branch.

# The report goes last, and is concatenated rather than substituted: it carries
# pytest's own output, where an assertion diff over a dict is full of braces and
# str.format would raise on the first one.
_FIX_UNCOVERED = """\
diff-cover reports lines this branch changed that no test exercises. Validate
them and decide what each one needs:

- unreachable or dead code — ask me what to do with it
- uncovered lines in gates — write an integration test
- uncovered lines in mills — write a unit test

Ask me rather than guessing whenever the call is mine to make: an unclear
intent, a test that belongs somewhere the layout does not obviously cover, a
line that looks deliberately unreachable. Do not lower the coverage threshold,
edit the coverage configuration, or delete the offending code.

The report:

"""


class CoverDiff(BaseModel):
    bound: int = 3


class Uncovered(BaseModel):
    budget: int
    report: str = ""


class CoverReport(BaseModel):
    covered: bool
    remaining: int


@ritual("cover_diff")
async def cover_diff(components: CoverDiff) -> Transition:
    # The entrypoint: map the CLI Components into the first step's payload.
    return goto(measure, Uncovered(budget=components.bound))


@step
async def measure(state: Uncovered) -> Transition:
    # `mise run diff-cover` runs the suite under coverage, then fails when the
    # lines this branch changed are not exercised by a test.
    result = await shell("mise run diff-cover --fail-under 100")
    if result.exit_code == 0:
        return done(CoverReport(covered=True, remaining=state.budget))
    if state.budget == 0:
        return done(CoverReport(covered=False, remaining=0))
    return goto(write_tests, Uncovered(budget=state.budget, report=result.stdout))


@step
async def write_tests(state: Uncovered) -> Transition:
    # The report names the uncovered lines, so the agent gets the failure
    # rather than a description of it.
    await coding(_FIX_UNCOVERED + state.report)
    return goto(measure, Uncovered(budget=state.budget - 1))


# review — read the diff this branch adds, and say what is wrong with it.

_REVIEW_SYSTEM = """\
You are reviewing a diff on this repository, and only what the diff changes.
Read CLAUDE.md and docs/architecture.md first: this project has layering rules,
naming rules and a definition of done that a diff can break while looking
innocent on its own. Your tools are read-only. Report what you find; change
nothing.
"""

_REVIEW = """\
Review the diff below and return the findings you can defend.

A finding names where it is, what is wrong, and how much it matters:
"blocker" for something that breaks a contract, a layer, or the gates; "risk"
for what will bite later; "nit" for the rest. An empty findings list is a valid
answer, and a better one than padding.

"""


class ReviewRequest(BaseModel):
    base: GitRef = "main"
    only: File | None = None
    focus: Text = ""


class Diff(BaseModel):
    base: str
    text: str
    focus: str = ""
    pinned: str | None = None


class Finding(BaseModel):
    where: str
    what: str
    severity: Literal["blocker", "risk", "nit"]


# What the agent returns, and no more: the provenance below is the ritual's to
# state, not the agent's to invent.
class Judgement(BaseModel):
    verdict: Literal["ship", "fix"]
    findings: list[Finding]


class Review(BaseModel):
    base: str
    verdict: Literal["ship", "fix"]
    findings: list[Finding]
    pinned: str | None = None


@ritual("review")
async def review(components: ReviewRequest) -> Transition:
    # The components are already the first step's payload — there is nothing to
    # map, so nothing is mapped.
    return goto(collect, components)


@step
async def collect(request: ReviewRequest) -> Transition:
    scope = f" -- {request.only}" if request.only is not None else ""
    # stream=False: a diff is bulk, not progress. It reaches the agent in the
    # next step either way.
    result = await shell(f"git diff {request.base}...HEAD{scope}", stream=False)
    if result.exit_code:
        msg = f"git diff against {request.base!r} failed: {result.stderr.strip()}"
        raise RitualError(msg)
    # Nothing changed is an answer, and not one worth paying an agent for.
    if not result.stdout.strip():
        return done(Review(base=request.base, verdict="ship", findings=[]))
    return goto(
        judge,
        Diff(
            base=request.base,
            text=result.stdout,
            focus=request.focus,
            # `File` has already checked it is readable, so the hash pins the
            # review to the exact bytes that were reviewed.
            pinned=None if request.only is None else sha256_of(request.only),
        ),
    )


@step
async def judge(diff: Diff) -> Transition:
    focus = f"Pay particular attention to: {diff.focus}\n\n" if diff.focus else ""
    judgement = await coding(
        f"{_REVIEW}{focus}base: {diff.base}\n\n{diff.text}",
        output=Judgement,
        opts=CodingOpts(system=_REVIEW_SYSTEM),
        # Read-only, enforced rather than requested: `dontAsk` denies anything
        # outside the allowlist without stopping to prompt. Not `plan`, which
        # executes no tools at all — the reviewer could not read CLAUDE.md.
        focus_options=ClaudeOptions(
            permission_mode="dontAsk",
            allowed_tools=["Read", "Grep", "Glob"],
            effort="high",
        ),
    )
    return done(
        Review(
            base=diff.base,
            verdict=judgement.verdict,
            findings=judgement.findings,
            pinned=diff.pinned,
        )
    )


# merge_ready — run both gates at once, and babysit them to green.

_REPAIR = """\
`mise run prcheck` and `mise run test` are this project's gates, and what
follows is what they said. Make them green.

Fix the cause, not the symptom: do not disable a lint rule, add a noqa or a
type: ignore, skip or delete a test, or lower a threshold. Ask me rather than
guessing when the choice is mine — a failing assertion that may be the test's
fault rather than the code's, for one.

"""


class MergeReady(BaseModel):
    bound: int = 3


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


def _red(*, budget: int, lint: ShellResult, suite: ShellResult) -> Red:
    if lint.exit_code and suite.exit_code:
        return BothRed(budget=budget, lint=lint.stdout, suite=suite.stdout)
    if lint.exit_code:
        return LintFailure(budget=budget, lint=lint.stdout)
    return SuiteFailure(budget=budget, suite=suite.stdout)


def _complaint(failure: Red) -> str:
    if isinstance(failure, BothRed):
        return f"The linters said:\n\n{failure.lint}\n\nThe suite said:\n\n{failure.suite}"
    if isinstance(failure, LintFailure):
        return f"The linters said:\n\n{failure.lint}"
    return f"The suite said:\n\n{failure.suite}"


# max_steps is the backstop, not the control — the bound is. It sits well above
# a plausible bound, so tripping it means a ritual that will not settle.
@ritual("merge_ready", max_steps=32)
async def merge_ready(components: MergeReady) -> Transition:
    return goto(gates, Attempt(budget=components.bound))


@step
async def gates(state: Attempt) -> Transition:
    # Both gates take minutes, and neither reads the other's output. Running
    # them at once is not only faster: one cast then tells you everything that
    # is red, rather than the first thing that is red.
    async with asyncio.TaskGroup() as group:
        linting = group.create_task(shell("mise run prcheck"))
        suite = group.create_task(shell("mise run test"))
    lint, tests = linting.result(), suite.result()
    if not lint.exit_code and not tests.exit_code:
        return done(MergeReport(green=True, remaining=state.budget))
    if state.budget == 0:
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
@step
async def repair(failure: Red) -> Transition:
    await coding(_REPAIR + _complaint(failure))
    return goto(gates, Attempt(budget=failure.budget - 1))
