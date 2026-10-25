# ci_watch — read one pull request's CI and, while it is red and fixes are
# left, wait on a `pr_fix` and read it again.

from typing import Literal

from pydantic import BaseModel

from vekna.folio.flow import await_cast, timeout
from vekna.folio.shell import shell
from vekna.lexicon import Done, Failure, RitualError, ritual, step

from .pr_fix import CiFix, Fixed, Seconds
from .shared import Bound, said

# `gh pr checks` exits 8 while a check is pending, which `--watch` waits out, so
# anything but 0 or 1 is gh failing rather than CI.
_GREEN, _RED = 0, 1


class CiWatch(BaseModel):
    pull_request: int
    fixes: Bound = 2
    patience: Seconds = 3600


class Watched(BaseModel):
    pull_request: int
    outcome: Literal["green", "out of fixes", "fix not pushed", "failed"]
    detail: str = ""


@ritual("ci_watch", max_steps=32)
def ci_watch(components: CiWatch) -> CiWatch:
    return components


@step
async def watch(state: CiWatch) -> CiWatch | Done[Watched]:
    # Bounded by the clock, not by gh: a check stuck pending would otherwise hold
    # this cast's slot forever. An overrun raises, and `gave_up` takes it.
    checks = await timeout(
        shell(f"gh pr checks {state.pull_request} --watch", stream=False),
        seconds=state.patience,
    )
    if checks.exit_code == _GREEN:
        return Done(Watched(pull_request=state.pull_request, outcome="green"))
    if checks.exit_code != _RED:
        msg = f"reading the checks on #{state.pull_request} failed: {said(checks)}"
        raise RitualError(msg)
    if state.fixes <= 0:
        return Done(Watched(pull_request=state.pull_request, outcome="out of fixes"))
    # Awaited rather than enqueued: the verdict on this pull request is this
    # cast's to give, and it is not given until the fix is in. While it waits it
    # holds no process slot, so a fix queued behind it is not starved by its own
    # parent. `remote` is left unset: an unset component takes
    # `[defaults.pr_fix]` where the child runs.
    fixed = await await_cast(
        "pr_fix",
        CiFix(pull_request=state.pull_request, checks=checks.stdout),
        output=Fixed,
    )
    if fixed.outcome != "pushed":
        return Done(
            Watched(
                pull_request=state.pull_request,
                outcome="fix not pushed",
                detail=fixed.outcome,
            )
        )
    # The push restarts CI, so the verdict is the checks' again.
    return CiWatch(
        pull_request=state.pull_request, fixes=state.fixes - 1, patience=state.patience
    )


# A fix cast that failed, a timeout or a broken gh is an answer about the pull
# request, not a reason for the watch to fail with it.
@step
def gave_up(failure: Failure[CiWatch]) -> Done[Watched]:
    return Done(
        Watched(
            pull_request=failure.payload.pull_request,
            outcome="failed",
            detail=failure.error.message,
        )
    )
