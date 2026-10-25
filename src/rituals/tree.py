# tree — a cast that runs in a pooled worktree and says which, for exercising
# the pool from the dashboard (lease, park, block) without paying an agent.

from pydantic import BaseModel

from vekna.lexicon import Done, ritual, step

from .shared import ran

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
    result = await ran(
        "git rev-parse --show-toplevel && git branch --show-current",
        doing="reading the tree",
    )
    # A detached HEAD prints no branch line.
    root, _, branch = result.stdout.rstrip("\n").partition("\n")
    if state.dirty:
        await ran(f"echo dirt > {DIRT}", doing=f"leaving {DIRT}")
    return Done(Stood(root=root, branch=branch, dirty=state.dirty))
