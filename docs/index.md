# vekna

Run coding agents as **rituals**: ordinary Python programs whose steps you
control and whose agent calls happen inside those steps. Agents run
permissively *within* a step; determinism lives at the step boundaries.

An agent left to plan its own work is impressive right up to the point where it
decides the failing test was the problem. A ritual is the other arrangement:
you write the loop, the branches and the stopping condition yourself, and hand
the agent one bounded piece of work at a time.

Nothing about that keeps a ritual short. The one below fits on a screen because
it is an introduction; a ritual that has been in daily use for a while is a
package with a test suite, and the [rituals page](rituals.md) is about splitting
one up. What stays true at any size is that the control flow is yours to read.

## Install

```bash
pip install vekna
```

Python 3.11 or newer. The `coding` medium reaches an agent through the
[Claude Code CLI](https://docs.claude.com/en/docs/claude-code/setup), which
installs separately — everything else works without it.

## Your first ritual

Put a `rituals.py` in your project:

```python
from typing import Annotated

from pydantic import BaseModel, Field

from vekna.folio.coding import coding
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step


class FixTests(BaseModel):
    # A retry budget counts down to zero, so the CLI rejects a negative one
    # rather than letting `--bound -1` run until the step backstop.
    bound: Annotated[int, Field(ge=0)] = 3


class Attempt(BaseModel):
    left: int


class Verdict(BaseModel):
    outcome: str


@step
async def fix(state: Attempt) -> Transition:
    result = await shell("pytest")
    if result.exit_code == 0:
        return done(Verdict(outcome="green"))
    if state.left <= 0:
        return done(Verdict(outcome="gave up"))
    await coding(f"The test suite fails:\n{result.stdout}\nFix it.")
    return goto(fix, Attempt(left=state.left - 1))


# `def`, not `async def`: naming the first step has nothing to await. A step or
# entrypoint is written whichever way its body needs.
@ritual("fix_tests")
def fix_tests(components: FixTests) -> Transition:
    return goto(fix, Attempt(left=components.bound))
```

Then cast it:

```bash
vekna cast fix_tests --bound 5
```

Output streams live as a tree of rites — one node per step, one nested under
it per medium call, with the agent's own output indented beneath. The last
line is the cast's result, as JSON:

```text
result: {"outcome":"green"}
```

That is the whole shape of the thing. The retry budget is a number you wrote,
the stopping condition is an `if` you can read, and the agent is called once
per attempt with exactly what you chose to tell it.

## Where to go next

- [Rituals](rituals.md) — steps, transitions, components, and how a ritual is
  found.
- [Mediums](mediums.md) — `coding`, `shell` and `decide`, and how to configure
  the agent behind them.
- [Testing rituals](testing.md) — run a ritual with every medium answering from
  a script.
- [Examples](examples.md) — the rituals this project runs on itself.
- [Safety](safety.md) — what vekna does not sandbox. Worth reading before your
  first cast.
