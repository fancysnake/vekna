# sweep — the factory in three rituals. `sweep` lists the open pull requests
# and queues one `ci_watch` per pull request; `ci_watch` reads its CI and, when
# it is red, waits on a `pr_fix`; `pr_fix` is the only one that needs a tree.
# Parallelism is between those casts, as many as `[circle]` allows; each one's
# steps stay sequential.

import shlex

from pydantic import BaseModel, Field, TypeAdapter

from vekna.folio.flow import enqueue
from vekna.lexicon import Done, GitRef, ritual, step

from .ci_watch import CiWatch
from .shared import Bound, ran


class Sweep(BaseModel):
    # Which branch counts as a pull request's base is the repository's answer,
    # not the run's: `[defaults.sweep]` in `.vekna.toml` gives it.
    base_branch: GitRef
    max_prs: Bound = 10


class Listed(BaseModel):
    number: int
    cross_repository: bool = Field(alias="isCrossRepository")


_LISTED = TypeAdapter(list[Listed])
# Forks are dropped after listing, so gh lists past `max_prs` to leave the budget
# to pull requests that can be queued.
_LIST_LIMIT = 1000


class Queued(BaseModel):
    pull_request: int
    cast_id: str


class Swept(BaseModel):
    queued: list[Queued]


# A sweep needs no tree: it reads a list and queues casts, and each of those
# says for itself whether it needs one.
@ritual("sweep")
def sweep(components: Sweep) -> Sweep:
    return components


@step
async def fan_out(request: Sweep) -> Done[Swept]:
    base = shlex.quote(request.base_branch)
    found = await ran(
        f"gh pr list --base {base} --limit {_LIST_LIMIT}"
        " --json number,isCrossRepository",
        doing=f"listing pull requests against {request.base_branch}",
        stream=False,
    )
    # Forks are left out: `pr_fix` would refuse each one, and a watch that can
    # only end in that refusal is a slot spent on nothing.
    numbers = [
        listed.number
        for listed in _LISTED.validate_json(found.stdout)
        if not listed.cross_repository
    ][: request.max_prs]
    # Enqueued, not awaited: the sweep is done once each pull request has a cast
    # of its own, and those run as slots free up rather than one after another.
    queued = [
        Queued(
            pull_request=number,
            cast_id=await enqueue("ci_watch", CiWatch(pull_request=number)),
        )
        for number in numbers
    ]
    return Done(Swept(queued=queued))
