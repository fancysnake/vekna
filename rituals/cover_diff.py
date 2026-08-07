# cover_diff — close the coverage gap on this branch.

from pydantic import BaseModel

from vekna.folio.coding import coding
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step

from .prompts import FIX_UNCOVERED
from .shared import Bound


class CoverDiff(BaseModel):
    bound: Bound = 3


class Uncovered(BaseModel):
    budget: int
    report: str = ""


class CoverReport(BaseModel):
    covered: bool
    remaining: int


@ritual("cover_diff")
def cover_diff(components: CoverDiff) -> Transition:
    # The entrypoint: map the CLI Components into the first step's payload.
    return goto(measure, Uncovered(budget=components.bound))


@step
async def measure(state: Uncovered) -> Transition:
    # `test:py:cov:diff` runs the suite under coverage, then fails when the
    # lines this branch changed are not exercised by a test.
    result = await shell("mise run test:py:cov:diff -- --fail-under 100")
    if result.exit_code == 0:
        return done(CoverReport(covered=True, remaining=state.budget))
    # `<=`, not `==`: the Components reject a negative bound, and this stays
    # right even if a future step arrives at one some other way.
    if state.budget <= 0:
        return done(CoverReport(covered=False, remaining=0))
    return goto(write_tests, Uncovered(budget=state.budget, report=result.stdout))


@step
async def write_tests(state: Uncovered) -> Transition:
    # The report names the uncovered lines, so the agent gets the failure
    # rather than a description of it.
    await coding(FIX_UNCOVERED + state.report)
    return goto(measure, Uncovered(budget=state.budget - 1))
