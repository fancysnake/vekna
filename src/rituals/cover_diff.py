# cover_diff — close the coverage gap on this branch.

from pydantic import BaseModel

from vekna.folio.coding import CodingOpts, coding
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step

from .shared import Bound, said

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
    bound: Bound = 3


class Uncovered(BaseModel):
    budget: int
    report: str = ""


class CoverReport(BaseModel):
    covered: bool
    remaining: int
    report: str = ""


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
    report = said(result)
    # `<=`, not `==`: the Components reject a negative bound, and this stays
    # right even if a future step arrives at one some other way. The report
    # rides out with the failure — a cast that gave up still has to say on what.
    if state.budget <= 0:
        return done(CoverReport(covered=False, remaining=0, report=report))
    return goto(write_tests, Uncovered(budget=state.budget, report=report))


@step
async def write_tests(state: Uncovered) -> Transition:
    # The report names the uncovered lines, so the agent gets the failure
    # rather than a description of it.
    # Every command the agent runs is put to you first: without `gate_tools`
    # the call defaults to bypassPermissions, which is a lot of trust to hand
    # an agent whose brief is "make the coverage number go up".
    await coding(_FIX_UNCOVERED + state.report, opts=CodingOpts(gate_tools=["Bash"]))
    return goto(measure, Uncovered(budget=state.budget - 1))
