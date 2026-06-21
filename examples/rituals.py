"""Worked example for ``vekna cast`` (standalone, no daemon).

Run it from this directory:

    vekna cast fix_demo --bound 3

``fix_demo`` is a guarded fix loop: it checks whether the work is done
(``shell``), and while it isn't, asks you whether to apply a fix (``decide``)
and loops back until the check passes or the attempt budget runs out.
"""

from pydantic import BaseModel

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
        prompt=f"not fixed yet ({attempt.budget} attempts left) — apply a fix?",
        options=["fix", "stop"],
    )
    if choice == "stop":
        return done(Report(fixed=False, remaining=attempt.budget))
    return goto(apply_fix, attempt)


@step
async def apply_fix(attempt: Attempt) -> Transition:
    await shell("touch .fixed")
    return goto(check, Attempt(budget=attempt.budget - 1))
