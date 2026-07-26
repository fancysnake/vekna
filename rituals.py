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

from pydantic import BaseModel

from vekna.folio.coding import coding
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step


_FIX_UNCOVERED = """\
diff-cover reports lines this branch changed that no test exercises.

{report}

Validate them and decide what each one needs:

- unreachable or dead code — ask me what to do with it
- uncovered lines in gates — write an integration test
- uncovered lines in mills — write a unit test

Ask me rather than guessing whenever the call is mine to make: an unclear
intent, a test that belongs somewhere the layout does not obviously cover, a
line that looks deliberately unreachable. Do not lower the coverage threshold,
edit the coverage configuration, or delete the offending code.
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
    await coding(_FIX_UNCOVERED.format(report=state.report))
    return goto(measure, Uncovered(budget=state.budget - 1))
