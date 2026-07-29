# vekna

Run coding agents as **rituals**: small Python programs whose steps you
control and whose agent calls happen inside those steps. Agents run
permissively *within* a step; determinism lives at the step boundaries.

## Requires

- Python 3.11+

## Install

```bash
pip install .
```

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
    result = await shell("mise run test")
    if result.exit_code == 0:
        return done(Verdict(outcome="green"))
    if state.left <= 0:
        return done(Verdict(outcome="gave up"))
    await coding(f"The test suite fails:\n{result.stdout}\nFix it.")
    return goto(fix, Attempt(left=state.left - 1))


@ritual("fix_tests")
async def fix_tests(components: FixTests) -> Transition:
    return goto(fix, Attempt(left=components.bound))
```

Then cast it:

```bash
vekna cast fix_tests --bound 5
```

Output streams live as a tree of rites — one node per step, one nested under
it per medium call, with the agent's own output indented beneath. The last
line is the cast's result, as JSON:

```
result: {"outcome":"green"}
```

## Commands

| Command | What it does |
| --- | --- |
| `vekna cast <ritual> [--<component> value …]` | Run a ritual from `rituals.py` |
| `vekna cast --prompt "<text>"` | One-shot cast on the coding medium, no `rituals.py` needed |
| `vekna rituals list` | Every ritual and the options it takes |
| `vekna rituals show <ritual>` | A ritual's components and its step graph |

## Concepts

- **Ritual** — a named program. Its components become `--options`.
- **Component** — what a ritual needs before it can be cast, the way a spell
  needs its material components. Typed values on the ritual's external
  interface — `File`, `Directory`, `Text`, `Url`, `GitRef` — declared as fields
  on one pydantic model, the ritual's only parameter.
- **Step** — one deterministic hop. Takes a typed payload, returns `goto(...)`
  or `done(...)`. A ritual is a trampoline over steps, bounded by `max_steps`.
- **Transition** — what a step returns. Both carry a pydantic model or nothing,
  checked as they are built: `goto(next_step, payload)` continues, `done(result)`
  finishes. A step may admit several payload shapes (`Lint | Coverage`); a
  ritual's components are one model, being one CLI interface.
- **Medium** — what a step reaches out to: `coding` (an agent), `shell`,
  `decide` (ask the operator). Each call opens a rite of its own. A step may
  hold several at once — `asyncio.TaskGroup` over two `shell` calls runs both
  and waits for both — and each still gets its own rite, so the grimoire records
  what actually happened concurrently. Steps themselves stay sequential.
- **Focus** — the backend behind a medium. `vekna.folio.coding_claude` is the
  Claude Agent SDK focus for `coding`.
- **Grimoire** — the event log of a cast: rites started, output deltas, rites
  finished, each with its status.

## Where rituals come from

`rituals.py` — or a `rituals/` package — in the current directory or any
parent. A package is searched all the way down, so its `__init__.py` can stay
empty and you can split it by ritual, by kind, or not at all. A `.vekna.toml`
(project) or `~/.config/vekna/config.toml` (global) can name more, resolved
relative to the config file:

```toml
[rituals]
files = ["ops/release.py"]
modules = ["mycompany.rites"]
```

## Configuring the agent

```python
from vekna.folio.coding import CodingOpts, coding
from vekna.folio.coding_claude import ClaudeOptions

# Portable knobs
await coding("refactor this", opts=CodingOpts(model="opus", cwd="./svc"))

# Ask before the agent runs a tool
await coding("clean the build", opts=CodingOpts(gate_tools=["Bash"]))

# Which thread of agent memory this call is on
await coding("try again", session="continue")

# Typed output, validated on return
class Plan(BaseModel):
    steps: int

plan = await coding("plan the migration", output=Plan)

# Focus-specific knobs
await coding("survey the code", focus_options=ClaudeOptions(
    permission_mode="dontAsk", allowed_tools=["Read", "Grep"], effort="high"
))
```

`dontAsk` with an allowlist is how you get a read-only agent: everything
outside the list is denied without stopping to ask you. Not `permission_mode=
"plan"`, which executes no tools at all — an agent in plan mode cannot read the
files you gave it `Read` for.

An agent can hand a decision back to you mid-rite by calling the `ask_human`
tool; the cast blocks until you answer.

### Sessions

Two `coding` calls in one cast either share the agent's context or they do not,
and `session` is where you say which:

| `session=` | what the call gets |
| --- | --- |
| `"new"` (default) | a fresh context |
| `"continue"` | the cast's last agent call, carried on |
| any other string | a named thread, resumed by that name |

A retry wants `continue` or a name — an agent remembering what it already tried
is the whole value. A review step wants `new`: an agent that helped write the
code is not a reviewer of it, and sharing silently makes that step worthless
while looking like it ran. The default is `new` because a step is a task
boundary, and carrying context across one by default contradicts what the
boundary is for.

Prefer a name over `continue` for a loop. They are the same thing while a
ritual has one agent call, and stop being the same the moment it gains a
second.

## Architecture

GLIMPSE layering, enforced by `import-linter`. See
[`docs/architecture.md`](docs/architecture.md) and
[`docs/reborn/`](docs/reborn/) for the release-by-release plan.

## Development

```bash
mise run test    # all tests
mise run check   # format + lint + types + import contracts
```

## Licence

BSD-3-Clause.
