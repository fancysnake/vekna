# Rituals

A ritual is a named program made of steps. Casting one runs it to completion
and prints its result.

## The vocabulary

- **Ritual** — a named program. Its components become `--options`.
- **Component** — what a ritual needs before it can be cast, the way a spell
  needs its material components. Typed values on the ritual's external
  interface — `File`, `Directory`, `Text`, `Url`, `GitRef` — declared as fields
  on one pydantic model, the ritual's only parameter.
- **Step** — one deterministic hop. Takes a typed payload, returns `goto(...)`
  or `done(...)`. A ritual is a trampoline over steps, bounded by `max_steps`.
- **Transition** — what a step returns. Both carry a pydantic model or nothing,
  checked as they are built: `goto(next_step, payload)` continues,
  `done(result)` finishes.
- **Medium** — what a step reaches out to: `coding` (an agent), `shell`,
  `decide` (ask the operator). Each call opens a rite of its own.
- **Focus** — the backend behind a medium. `vekna.folio.coding_claude` is the
  Claude Agent SDK focus for `coding`.
- **Grimoire** — the event log of a cast: rites started, output deltas, rites
  finished, each with its status.
- **Tome** — a ritual library published as an installable package, so several
  projects cast the same rituals from a versioned dependency rather than from
  copied files. See [below](#tomes-rituals-you-install).

## Steps and transitions

A step takes one payload and returns one transition. Nothing else is a step's
business — no shared mutable state between them, no hidden control flow.

```python
@step
async def review(state: Diff) -> Transition:
    if state.lines > 500:
        return done(Verdict(outcome="too big to review"))
    return goto(comment, Findings(text=await coding(f"Review:\n{state.body}")))
```

A step may admit several payload shapes — `Lint | Coverage` — which is how two
different predecessors hand work to one successor. A ritual's components stay
one model, because they are one CLI interface.

`max_steps` bounds the trampoline. A ritual that loops forever stops with
`StepBudgetExceededError` rather than running until you notice.

## Components become flags

The ritual's single parameter is a pydantic model, and each field becomes an
option:

```python
class Review(BaseModel):
    base: str = "main"
    only: Path | None = None
```

```bash
vekna cast review --base develop --only src/
```

Validation is pydantic's. A field typed `Annotated[int, Field(ge=0)]` rejects
`--bound -1` at the boundary rather than halfway through the third step, and
the error names the field.

`vekna rituals list` prints every ritual with the options it takes;
`vekna rituals show <name>` adds the step graph, drawn from the `goto` calls in
each step's body.

## Concurrency inside a step

A step may hold several medium calls at once — an `asyncio.TaskGroup` over two
`shell` calls runs both and waits for both — and each still gets its own rite,
so the grimoire records what actually happened concurrently. Each rite quotes
its own command, which is what tells the two lines apart.

```python
@step
async def gates(state: Branch) -> Transition:
    async with asyncio.TaskGroup() as group:
        lint = group.create_task(shell("mise run lint:py"))
        tests = group.create_task(shell("mise run test:py"))
    ...
```

Steps themselves stay sequential. The boundary between two steps is the thing
that makes a ritual reproducible, and running two of them at once would give
that up.

## Where rituals come from

A `rituals.py` — or a `rituals/` package — in the current directory or any
parent. A package is searched all the way down, so its `__init__.py` can stay
empty and you can split it by ritual, by kind, or not at all.

Two rules worth knowing before they bite:

- **Every level needs its own `__init__.py`** to be searched. A directory
  without one is not a package, and its rituals are invisible.
- **A directory holding both a `rituals.py` and a `rituals/` is an error**
  naming both, rather than a precedence rule quietly picking one. A
  half-finished move is the case this exists for.

A `.vekna.toml` (project) or `~/.config/vekna/config.toml` (global) can name
more, resolved relative to the config file:

```toml
[rituals]
files = ["ops/release.py"]
modules = ["mycompany.rites"]
```

These are additive: naming the file that would have been found anyway is how
you are explicit about it, and loading it twice is not an error. Two
*different* sources claiming one ritual name still is, and so are two of them
declaring a step of the same name — both errors name the pair rather than
letting whichever loaded first win.

## Tomes: rituals you install

A **tome** is a ritual library published as a package. `modules` names something
importable, not something on disk nearby — so a tome distributes like any other
Python dependency. Build a wheel, put it on your index, and every project that
installs it gets the same rituals:

```toml
# .vekna.toml, in each project that wants them
[rituals]
modules = ["mycompany.rites"]
```

```bash
pip install mycompany-rites
vekna cast housekeeping --depth 2
```

The project directory then needs nothing but that `.vekna.toml`. The package is
swept exactly as a local `rituals/` is — every submodule, all the way down — so
relative imports inside it resolve and `rituals show` draws the whole graph
rather than stopping at whatever `__init__.py` happened to re-export.

Two things to know:

- **It installs into the same environment as vekna.** The `vekna` command runs
  on its own interpreter, and a package your project can import is not
  automatically one that interpreter can. Installing vekna with `pipx` or `uv
  tool` means injecting the ritual package into that same environment rather
  than into the project's.
- **Every level still needs an `__init__.py`.** A namespace package has no
  directory for the sweep to walk, so its submodules are invisible — the same
  rule as a local `rituals/`, with the same silence if you skip it.

A tome carries its own test suite — `vekna[trial]` runs against the rituals
inside it, with no repository that casts them involved.

The word is for prose, not for the config key: `modules` takes a Python module
path and resolves the cwd as well as the environment, so `mycompany.rites`
loads whether it arrived from a wheel or sits in your own `src/`.
