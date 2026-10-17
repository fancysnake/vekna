# tree — a cast that runs in a pooled worktree and says which, for exercising
# the pool from the dashboard (lease, park, block) without paying an agent.

from pydantic import BaseModel

from vekna.folio.shell import shell
from vekna.lexicon import Done, RitualError, ritual, step

from .shared import said

# Untracked, so the tree reads dirty after the cast and is left blocked.
DIRT = "tree.dirt"


class Tree(BaseModel):
    dirty: bool = False


class Look(BaseModel):
    dirty: bool


class Stood(BaseModel):
    root: str
    branch: str
    dirty: bool


@ritual("tree", worktree=True)
def tree(components: Tree) -> Look:
    return Look(dirty=components.dirty)


@step
async def look(state: Look) -> Done[Stood]:
    result = await shell("git rev-parse --show-toplevel && git branch --show-current")
    if result.exit_code:
        msg = f"reading the tree failed: {said(result)}"
        raise RitualError(msg)
    # A detached HEAD prints no branch line.
    root, _, branch = result.stdout.rstrip("\n").partition("\n")
    if state.dirty and (left := await shell(f"echo dirt > {DIRT}")).exit_code:
        msg = f"leaving {DIRT} failed: {said(left)}"
        raise RitualError(msg)
    return Done(Stood(root=root, branch=branch, dirty=state.dirty))
