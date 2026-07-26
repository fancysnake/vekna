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

from typing import Literal

from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, coding
from vekna.folio.coding_claude import ClaudeOptions
from vekna.folio.shell import shell
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
