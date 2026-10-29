# vekna

[![PyPI](https://img.shields.io/pypi/v/vekna)](https://pypi.org/project/vekna/)
[![Python](https://img.shields.io/pypi/pyversions/vekna)](https://pypi.org/project/vekna/)
[![CI](https://github.com/fancysnake/vekna/actions/workflows/ci.yml/badge.svg)](https://github.com/fancysnake/vekna/actions/workflows/ci.yml)
[![License](https://img.shields.io/pypi/l/vekna)](LICENSE)

Run coding agents as **rituals**: ordinary Python programs whose steps you
control and whose agent calls happen inside those steps. Agents run
permissively *within* a step; determinism lives at the step boundaries.

Documentation is at [vekna.fancysnake.dev](https://vekna.fancysnake.dev).

![The vekna window: casts by ritual on the left, a pr_fix cast waiting on a
push decision on the right](https://raw.githubusercontent.com/fancysnake/vekna/main/docs/assets/tui.svg)

## Install

```bash
pip install vekna
```

Python 3.11+. Testing your rituals needs the `trial` extra:
`pip install 'vekna[trial]'` — quoted, because zsh globs the brackets.

## A ritual

Put a `rituals.py` in your project — or a `rituals/` package, split however you
like, once one file stops being enough:

```python
from typing import Annotated

from pydantic import BaseModel, Field

from vekna.folio.coding import coding
from vekna.folio.shell import shell
from vekna.lexicon import Done, ritual, step


class FixTests(BaseModel):
    # A retry budget counts down to zero, so the CLI rejects a negative one
    # rather than letting `--bound -1` run until the step backstop.
    bound: Annotated[int, Field(ge=0)] = 3


class Attempt(BaseModel):
    left: int


class Verdict(BaseModel):
    outcome: str


# The return annotation is the step's exits: back to `fix`, or finished with a
# `Verdict`. mypy checks every return against it, so a mis-wire fails the type
# check rather than a cast.
@step
async def fix(state: Attempt) -> Attempt | Done[Verdict]:
    result = await shell("mise run test:py")
    if result.exit_code == 0:
        return Done(Verdict(outcome="green"))
    if state.left <= 0:
        return Done(Verdict(outcome="gave up"))
    await coding(f"The test suite fails:\n{result.stdout}\nFix it.")
    return Attempt(left=state.left - 1)


# `def`, not `async def`: naming the first step has nothing to await. A step or
# entrypoint is written whichever way its body needs.
@ritual("fix_tests")
def fix_tests(components: FixTests) -> Attempt:
    return Attempt(left=components.bound)
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

## Claude Code plugin

The `ritual-scribe` skill teaches Claude Code to write rituals. Install it from
this repo's marketplace:

```bash
claude plugin marketplace add fancysnake/vekna
claude plugin install ritual-scribe@vekna
```

## Commands

| Command | What it does |
| --- | --- |
| `vekna cast <ritual> [--<component> value …]` | Run a ritual from `rituals.py` |
| `vekna cast --prompt "<text>"` | One-shot cast on the coding medium, no `rituals.py` needed |
| `vekna rituals list` | Every ritual and the options it takes |
| `vekna rituals show <ritual>` | A ritual's components and its step graph |

## Contributing

[`CONTRIBUTING.md`](.github/CONTRIBUTING.md) covers setup, the check loop,
where code goes, and pull requests. [`docs/README.md`](docs/README.md) is where
the ideas live.

## Licence

BSD-3-Clause.
