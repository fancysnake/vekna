# vekna

Run coding agents as **rituals**: ordinary Python programs whose steps you
control and whose agent calls happen inside those steps. Agents run
permissively *within* a step; determinism lives at the step boundaries.

Documentation is at [vekna.fancysnake.dev](https://vekna.fancysnake.dev).

## Install

```bash
pip install vekna
```

Python 3.11+. Testing your rituals needs the `trial` extra: `pip install
vekna[trial]`.

## A ritual

Put a `rituals.py` in your project — or a `rituals/` package, split however you
like, once one file stops being enough:

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
    result = await shell("mise run test:py")
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

## Commands

| Command | What it does |
| --- | --- |
| `vekna cast <ritual> [--<component> value …]` | Run a ritual from `rituals.py` |
| `vekna cast --prompt "<text>"` | One-shot cast on the coding medium, no `rituals.py` needed |
| `vekna rituals list` | Every ritual and the options it takes |
| `vekna rituals show <ritual>` | A ritual's components and its step graph |

## Architecture

[GLIMPSE](https://glimpse.fancysnake.dev/) layering, enforced by
`import-linter`. See
[`docs/architecture.md`](docs/architecture.md) and
[`docs/reborn/`](docs/reborn/) for the release-by-release plan.

## Development

```bash
mise run test:py     # all tests
mise run check:py    # the loop while you work: format, lint, tests
mise run fullcheck   # the gate before you push: adds diff-coverage and tingle
```

## Licence

BSD-3-Clause.
