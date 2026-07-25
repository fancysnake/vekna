# vekna

Run coding agents as **rituals**: small Python programs whose steps you
control and whose agent calls happen inside those steps. Agents run
permissively *within* a step; determinism lives at the step boundaries.

## Requires

- Python 3.10+

## Install

```bash
pip install .
```

## A ritual

Put a `rituals.py` in your project:

```python
from pydantic import BaseModel

from vekna.folio.coding import coding
from vekna.folio.shell import shell
from vekna.lexicon import Transition, done, goto, ritual, step


class Attempt(BaseModel):
    left: int


@step
async def fix(state: Attempt) -> Transition:
    result = await shell("mise run test")
    if result.exit_code == 0:
        return done("green")
    if not state.left:
        return done("gave up")
    await coding(f"The test suite fails:\n{result.stdout}\nFix it.")
    return goto(fix, Attempt(left=state.left - 1))


@ritual("fix_tests")
async def fix_tests(bound: int = 3) -> Transition:
    return goto(fix, Attempt(left=bound))
```

Then cast it:

```bash
vekna cast fix_tests --bound 5
```

Output streams live as a tree of rites — one node per step, one nested under
it per medium call, with the agent's own output indented beneath.

## Commands

| Command | What it does |
| --- | --- |
| `vekna cast <ritual> [--<component> value …]` | Run a ritual from `rituals.py` |
| `vekna cast --prompt "<text>"` | One-shot cast on the coding medium, no `rituals.py` needed |
| `vekna rituals list` | Every ritual and the options it takes |
| `vekna rituals show <ritual>` | A ritual's components and its step graph |

## Concepts

- **Ritual** — a named program. Its parameters become `--options`.
- **Step** — one deterministic hop. Takes a typed payload, returns `goto(...)`
  or `done(...)`. A ritual is a trampoline over steps, bounded by `max_steps`.
- **Medium** — what a step reaches out to: `coding` (an agent), `shell`,
  `decide` (ask the operator). Each call opens a rite of its own.
- **Focus** — the backend behind a medium. `vekna.folio.coding_claude` is the
  Claude Agent SDK focus for `coding`.
- **Grimoire** — the event log of a cast: rites started, output deltas, rites
  finished, each with its status.

## Where rituals come from

`rituals.py` in the current directory or any parent. A `.vekna.toml` (project)
or `~/.config/vekna/config.toml` (global) can name more, resolved relative to
the config file:

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
await coding("clean the build", gate_tools=["Bash"])

# Typed output, validated on return
class Plan(BaseModel):
    steps: int

plan = await coding("plan the migration", output=Plan)

# Focus-specific knobs
await coding("survey the code", focus_options=ClaudeOptions(
    permission_mode="plan", allowed_tools=["Read"], effort="high"
))
```

An agent can hand a decision back to you mid-rite by calling the `ask_human`
tool; the cast blocks until you answer.

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
