# nap — a cast that sleeps and calls nothing else, for exercising what watches
# casts (the dashboard, the daemon, `--continue`) without paying an agent.

from typing import Annotated

from pydantic import BaseModel, Field

from vekna.folio.shell import shell
from vekna.lexicon import Done, RitualError, ritual, step

from .shared import Bound, said


class Nap(BaseModel):
    naps: Bound = 4
    seconds: Annotated[int, Field(ge=0)] = 30


# The count rides in the payload, so a cast carried on with `--continue` replays
# the naps it already took and resumes counting where it was cut off.
class Asleep(BaseModel):
    left: int
    slept: int
    seconds: int


class Slept(BaseModel):
    naps: int


@ritual("nap")
def nap(components: Nap) -> Asleep:
    return Asleep(left=components.naps, slept=0, seconds=components.seconds)


@step
async def sleep(state: Asleep) -> Asleep | Done[Slept]:
    if state.left <= 0:
        return Done(Slept(naps=state.slept))
    result = await shell(f"sleep {state.seconds}")
    if result.exit_code:
        msg = f"nap {state.slept + 1} failed: {said(result)}"
        raise RitualError(msg)
    return Asleep(left=state.left - 1, slept=state.slept + 1, seconds=state.seconds)
