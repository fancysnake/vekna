---
description: "Write a vekna ritual: typed steps and transitions, failure routing, step budgets, components as CLI flags, and where rituals are discovered."
---

# Rituals

A ritual is a named program made of steps. Casting one runs it to completion
and prints its result.

/// html | div.diagram
    markdown: html

--8<-- "rituals.svg"
///

## The vocabulary

- **Ritual** — a named program. Its components become `--options`.
- **Component** — what a ritual needs before it can be cast, the way a spell
  needs its material components. Typed values on the ritual's external
  interface — `File`, `Directory`, `Text`, `Url`, `GitRef` — declared as fields
  on one pydantic model, the ritual's only parameter.
- **Step** — one deterministic hop. Takes a typed payload and returns the next
  step's payload, or `Done(result)`. A ritual is a trampoline over steps,
  bounded by `max_steps`.
- **Transition** — what a step returns. A payload *is* the next step: each
  payload class belongs to exactly one step, so returning `Attempt(...)` names
  the step that takes an `Attempt`. `Done[T]` finishes with a `T`. The step's
  return annotation lists its exits, and mypy checks every return against it.
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
async def review(state: Diff) -> Findings | Done[Verdict]:
    if state.lines > 500:
        return Done(Verdict(outcome="too big to review"))
    return Findings(text=await coding(f"Review:\n{state.body}"))
```

The return annotation is the declaration: `review` goes on to whichever step
takes a `Findings`, or ends with a `Verdict`. There is no second place for the
graph to live, so nothing drifts, and a step whose body returns something its
annotation does not name fails `mypy`, not a cast.

A step may admit several payload shapes — `Lint | Coverage` — which is how two
different predecessors hand work to one successor. A ritual's components stay
one model, because they are one CLI interface. The one rule: **a payload class
belongs to one step**. Two steps declaring the same class is an error naming
both.

`max_steps` bounds the trampoline. A ritual that loops forever stops with
`StepBudgetExceededError` rather than running until you notice.
`@step(max_visits=N)` caps how often one cast enters one step, which ends a
retry loop sooner than the whole budget would. Pick either cap by
[counting the steps](#show-the-arithmetic-behind-a-cap), not by guessing.
`@step(timeout=600)` bounds one visit in seconds: an overrun cancels the step's
work and fails it with `RiteTimeoutError`, which recovers like any other
failure.

`@step` returns a `Step`, importable from `vekna.lexicon` for annotations. It
carries only `name`, the function's name. Two steps may share a name, so key
per-step state, such as a retry budget, on it only while you keep yours unique.

`@ritual("fix", worktree=True)` asks for a checkout of its own: started from
the dashboard, the cast runs in a pooled worktree, not in the tree it was asked
from. [The CLI reference](cli.md#worktrees) has the pool.

## When a step fails

A step that raises ends the cast — unless some step takes `Failure[P]`, `P`
being the class of the payload that entered the failed step. Then the cast
goes there instead:

```python
@step(max_visits=4)
async def fix(attempt: Attempt) -> Tests:
    await coding(f"fix:\n{attempt.failures}")
    return Tests(budget=attempt.budget)


@step
def triage(failure: Failure[Attempt]) -> Attempt | Done[Report]:
    if failure.attempt >= 3:
        return Done(Report(fixed=False, reason=failure.error.message))
    return failure.payload.narrowed()
```

`Failure` carries the `payload` that entered, the `error` (type, message,
traceback), the `rite` that raised, and `attempt` — how many times this step
has failed in this cast. Recovery is an ordinary step: it declares its exits,
counts against `max_steps`, and a raise inside it goes to whichever step takes
`Failure[Failure[Attempt]]`, or ends the cast. A step never catches its own
failure.

`rituals show` draws the edge as `triage (on failure)`. A step whose payload is
a union fails into `Failure[A]` or `Failure[B]`, whichever entered.

**A failed cast still owes its report.** Route every ending, the fatal ones
included, through one final step that writes the summary with `emit_delta` and
then returns `Done` or raises. Four items fixed before the agent died is a
result; a bare `cast failed:` line throws it away.

```python
@step
def report(failure: Failure[Item]) -> Done[Summary]:
    emit_delta(f"stopped at {failure.payload.name}: {failure.error.message}")
    return Done(Summary(fixed=failure.payload.done_so_far))
```

`vekna cast --unattended` turns every `decide` into an
`UnattendedPromptError` raised inside the step, so a ritual meant for cron can
route it like any other failure. Or it can ask before asking: `attended()` is
false in such a cast.

```python
if not attended():
    emit_delta(f"{len(threads)} threads wait for you")
    return Done(summary)
```

## Failing over many items

A ritual cast by hand on one branch can stop at the first failure: you are
there to read it. A ritual cast every night over twenty pull requests cannot.
Nobody reads the traceback, and the next item is still owed its turn. Four
practices follow, all taken from
[cabinet](https://github.com/fancysnake/cabinet)'s `heal` rituals.

### The world decides, never the reply

An agent that answers "fixed" has told you what it believes. Route on what the
ritual can read back itself: the gate's exit code, the index, the file on disk.

```python
@step
async def repair(red: Red) -> Red | Landed | GaveUp:
    await coding(_REPAIR + red.said, session=Session.CONTINUE, key=red.branch)
    gate = await shell("mise run check")
    if not gate.exit_code:
        return Landed(branch=red.branch)
    if red.budget <= 1:
        return GaveUp(branch=red.branch, reason=gate.stdout, seen=red.seen)
    return red.model_copy(update={"budget": red.budget - 1, "said": gate.stdout})
```

The step throws the reply away. The gate runs after every round, and its exit
code alone chooses the exit. The same holds for a merge: ask git whether the
index is clean, not the agent whether it resolved the conflict.

A reply given through `output=Model` is a reading, and a reading is fair data:
which threads need an answer, which files conflict. It is not a verdict on
whether the work is done.

A step with nothing to read back has no retry loop. Where no command, file or
API can say whether the work happened, a second attempt is a second guess that
costs as much as the first. Run the agent once and report what it left.

### Three tiers of failure

Decide how far each failure reaches at the place it happens.

| Tier | Example | What the ritual does |
| --- | --- | --- |
| Fatal to the run | the worktree is dirty, the remote refuses the login | raise, and let the report step say what was done so far |
| Fatal to one item | the branch will not check out, the forge will not answer about this pull request | write the item's row as blocked, take the next item |
| Degraded | the item's gate will not go green, but its review can still be posted | stand down from that task, go on with the item's other tasks, report it red |

Only the first tier is a raise. The other two are payloads a step returns,
which makes them exits the annotation names and `rituals show` draws:

```python
async def sync_branch(work: SyncBranch) -> Chart | SkipPr | Tend: ...
```

Treat every failure as fatal and one stuck branch costs the nineteen behind it.
Drop the third tier and a branch whose gate stays red vanishes from the report,
when "still red, and here is what it said" is the line you wanted to read.

### Leave the world recoverable

Every path that gives up does three things: it aborts what is half done, it
stashes what the agent left under a name, and it puts the name in the report.

```python
_RELEASE = """\
if git rev-parse -q --verify MERGE_HEAD >/dev/null; then git merge --abort; fi
if [ -n "$(git status --porcelain)" ]; then
    git stash push -u -m {name} >/dev/null && echo stashed
fi
"""


@step
async def give_up(lost: GaveUp) -> NextItem:
    name = f"gave-up/{lost.branch}"
    ran = await shell(_RELEASE.format(name=shlex.quote(name)))
    stash = name if ran.stdout.strip() == "stashed" else ""
    row = Row(branch=lost.branch, reason=lost.reason, stash=stash)
    return NextItem(rows=[*lost.rows, row], seen=[*lost.seen, lost.reason])
```

Half a repair is not something to review, and the next item needs a clean tree
to start from. A stash without a name in the report is work nobody will find.
The script echoes its own word because `git stash push` exits 0 with nothing to
stash, so the exit code alone would report a stash that does not exist.

### Do not pay twice for one failure

When the base branch is red, every pull request that merges it fails the same
test. Spending a full repair budget on each buys the same verdict twenty times.

Carry the failures the cast gave up on in the payload, and compare each item's
first failure against them before the first repair:

```python
def same_failure(one: str, other: str) -> bool:
    return bool(one) and re.sub(r"\d+", "", one) == re.sub(r"\d+", "", other)


if any(same_failure(gate.stdout, known) for known in red.seen):
    return GaveUp(branch=red.branch, reason="red as it already was", seen=red.seen)
```

Compare normalised text. Timings, counts and timestamps differ on every run, so
two runs of one broken suite never match character for character; with the
digits gone, the failing test's name and the tool that named it remain. Ask
before the first repair, never after one, so that a match means "this item
arrived broken the same way" and not "the agent failed twice".

## Remembering and bounding across runs

A ritual cast every night meets the same pull requests again. It has to know
what it already did for each one, and how often it may retry before it stops.
Vekna keeps nothing between casts, so both answers live in the ritual. These
three practices come from cabinet's `heal` rituals too.

### A label remembers what the ritual did

Some work leaves a fact the next cast can read for free. A merged branch has no
conflict, and a repaired gate is green. That work needs no memory: the next
cast looks, finds nothing to do, and moves on.

Other work leaves nothing the listing shows. A posted review is a set of inline
comments, and the call that lists the night's pull requests does not return
them. Without a mark, the ritual reviews the same branch every night. A label
is the mark, because the listing already returns it:

```python
_REVIEWED = "reviewed"

listed = await shell("gh pr list --author @me --json number,labels", stream=False)
owed = [
    pull["number"]
    for pull in json.loads(listed.stdout)
    if _REVIEWED not in {label["name"] for label in pull["labels"]}
]
```

Put the label on last, after the review is posted. A cast that dies halfway
then leaves no label, and the next cast does the work again.

A label is also a switch you can reach. Take it off by hand and the next cast
reviews the branch again. Say so where the ritual is documented, because
nothing else tells the reader how to ask twice.

### One budget for each step, kept with the item

An item often passes through more than one retry loop: resolve the conflicts,
then repair the gate. One shared counter lets the first loop spend the attempts
of the second. Keep a count for each step, keyed on the step's name, in the
payload that carries the item:

```python
_ROUNDS = 3


class Repair(BaseModel):
    branch: str
    said: str
    spent: dict[str, int] = {}


@step
async def repair(work: Repair) -> Repair | Review | GaveUp:
    await coding(_REPAIR + work.said, session=Session.CONTINUE, key=work.branch)
    gate = await shell("mise run check")
    if not gate.exit_code:
        kept = {name: n for name, n in work.spent.items() if name != repair.name}
        return Review(branch=work.branch, spent=kept)
    spent = work.spent.get(repair.name, 0) + 1
    if spent >= _ROUNDS:
        return GaveUp(branch=work.branch, reason=gate.stdout)
    return work.model_copy(
        update={"said": gate.stdout, "spent": {**work.spent, repair.name: spent}}
    )
```

`repair.name` is the `Step` that `@step` returned, read inside its own body.
The key holds only while your step names are unique.

The green exit removes the step's count. An item can reach the same step twice
in one cast: a later merge turns the gate red again. The second visit is a new
problem and starts with a full budget, not with what the first visit left.

The counts die with the item. The next item starts from an empty `spent`, and
no file or label carries a count into the next cast. A branch that used every
round tonight gets every round tomorrow. That is deliberate: someone may have
pushed a fix in between.

### Show the arithmetic behind a cap

`max_steps` and `max_visits` stop a ritual that will not settle. A cap set
"well above anything plausible" is a guess, and it fails in both directions.
Too low, and a legal bound trips it: the engine raises
`StepBudgetExceededError` between steps, where no `Failure` step can take it,
so the cast ends with no report. Too high, and nobody can say whether the
number still means anything.

Count the steps the worst cast takes, and write the sum next to the cap:

```python
# A round is two steps, `measure` then `write_tests`, and one more `measure`
# reads the last round: 2 * bound + 1. 32 holds a bound of 15. A larger bound
# trips the cap first, and the cast ends with no report.
@ritual("cover_diff", max_steps=32)
def cover_diff(components: CoverDiff) -> Uncovered:
    return Uncovered(budget=components.bound)
```

Over many items the sum has the same shape: the steps one item can take at
worst, times the items, plus the steps that run once. Limit the listing
(`--limit 30`) so that the item count is a number you can put in the sum.

A cap of ten thousand is safe when the sum beside it comes to ten thousand. A
cap of thirty-two with no sum is not: the next author who raises a bound cannot
tell that the cap must rise with it.

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
`vekna rituals show <name>` adds the step graph, drawn from each step's return
annotation. An exit no step takes — a class you annotated but never decorated a
step with — is refused when the library loads, before anything is cast.

## Concurrency inside a step

A step may hold several medium calls at once — an `asyncio.TaskGroup` over two
`shell` calls runs both and waits for both — and each still gets its own rite,
so the grimoire records what actually happened concurrently. Each rite quotes
its own command, which is what tells the two lines apart.

```python
@step
async def gates(state: Branch) -> Red | Done[Report]:
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

A `.vekna.toml` (project) or `~/.config/vekna/config.toml` (user) can name
more, resolved relative to the config file. The user config can also hold a
table per project, so that a project needs no `.vekna.toml` at all:
[Scopes](scopes.md) covers that way of working.

```toml
[rituals]
files = ["ops/release.py"]
modules = ["mycompany.rites"]
```

These are additive: naming the file that would have been found anyway is how
you are explicit about it, and loading it twice is not an error. Two
*different* sources claiming one ritual name still is, and so are two steps
taking one payload class — both errors name the pair rather than letting
whichever loaded first win, and every ritual collision is reported in one go.
Two steps merely *named* alike are fine: a name routes nothing.

A `modules` entry that fails to import is skipped with a warning on stderr; the
rest still load. Asking for a ritual that is not there repeats why each skipped
module failed, and `rituals list` exits 1 while any is skipped. A broken file,
or a broken discovered `rituals.py`/`rituals/`, still stops the command.

## Component defaults

A component whose answer belongs to the repository rather than the run — the
base branch, `main` here and `master` there — goes in the config, one table per
ritual:

```toml
[defaults.pr_check]
base_branch = "main"
max_prs = 3

[defaults."mycompany:review"]   # a tome's ritual, quoted for the colon
depth = 2
```

Per key, a flag wins, then the project `.vekna.toml`, then your
`[projects.<name>]` table for the project in the user config, then the top
level of the user config ([which setting wins](scopes.md#which-setting-wins)).
TOML values arrive typed. A queued cast takes the defaults of the repo it runs
in for every component its enqueuer left unset. A default does not count as
set, so a ritual that hands its own components to `enqueue` passes on its flags
and nothing else. A field copied by name — `Child(remote=components.remote)` —
is set, whatever it came from.

`rituals show` prints a configured component with its value and file:

```text
  --base-branch <str>  = main (/home/me/work/app/.vekna.toml)
```

A key the ritual does not take fails the cast, naming the file, the ritual and
the key. A value of the wrong type fails `vekna rituals show` too, naming the
same. A table for a ritual not installed here is ignored, so a user config
can hold defaults for tomes some projects lack. Secrets stay out: `.vekna.toml`
is committed, so pass a credential as a flag.

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

**A tome's rituals carry its name.** The project's own stay bare; a tome's are
`<tome>:<name>`, so a tome and your project may both have a `review`:

```bash
vekna cast review            # the project's own
vekna cast mycompany:review  # the tome's
```

The tome is its top-level package unless you name it — a table instead of a
list, which is also how two tomes that would derive one name are told apart:

```toml
[rituals]
modules = { rites = "mycompany.rites" }
```

A tome's name must be a Python identifier. `:` belongs to the namespace, so
`@ritual` refuses a name that contains one.

A bare name finds the project's own ritual first, then the one tome that
offers it; offered by two tomes, it is an error naming both. `rituals list`
prints the project's rituals first, then each tome's, qualified.

The project directory then needs nothing but that `.vekna.toml`, and not even
that when the [user config](scopes.md) names the tome. The package is
swept exactly as a local `rituals/` is — every submodule, all the way down — so
relative imports inside it resolve and `rituals show` draws the whole graph
rather than stopping at whatever `__init__.py` happened to re-export.

Two things to know:

- **It installs into the same environment as vekna.** The `vekna` command runs
  on its own interpreter, and a package your project can import is not
  automatically one that interpreter can. Installing vekna with `pipx` or `uv
  tool` means injecting the ritual package into that same environment rather
  than into the project's. [One install for every project](scopes.md#install-once)
  shows the whole arrangement.
- **Every level still needs an `__init__.py`.** A namespace package has no
  directory for the sweep to walk, so its submodules are invisible — the same
  rule as a local `rituals/`, with the same silence if you skip it.

A tome with settings of its own reads them through
[`config_table`](scopes.md#for-tome-authors-read-your-table-through-vekna), so
they can be set wherever vekna reads config.

A tome carries its own test suite — `vekna[trial]` runs against the rituals
inside it, with no repository that casts them involved.

The word is for prose, not for the config key: `modules` takes a Python module
path and resolves the cwd as well as the environment, so `mycompany.rites`
loads whether it arrived from a wheel or sits in your own `src/`.
