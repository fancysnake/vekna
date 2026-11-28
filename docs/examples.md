---
description: "Where to read real vekna rituals: cabinet, the tome of pull request and issue rituals, and the rituals this project keeps to exercise its own engine."
---

# Examples

Real workflows live in [cabinet](https://cabinet.fancysnake.dev), a tome of
pull request and issue rituals: survey and heal every open pull request,
resolve merge conflicts, repair red CI, triage review threads, size the
backlog. Install it as a package and cast it from any repository on GitHub or
GitLab. Read it for how a ritual grows past one file.

The rituals below live in
[`src/rituals/`](https://github.com/fancysnake/vekna/tree/main/src/rituals) and
stay small on purpose: each exercises an engine feature, and this project casts
them on itself to prove the feature works.

Each says what credentials it needs. Scope a token to that and no further —
see [Safety](safety.md) for why that is the boundary worth having.

## `merge_ready` — run both gates at once, and babysit them to green

```bash
vekna cast merge_ready --bound 5
```

Runs lint and tests concurrently in one step — an `asyncio.TaskGroup` over two
`shell` calls, each getting its own rite — and on failure hands the output to
an agent with instructions to fix the cause rather than the symptom: no
disabled lint rule, no `noqa`, no skipped test, no lowered threshold. Loops
until green or until the retry budget runs out.

**Credentials:** none. It runs your own gates in your own checkout.

The repair thread uses `Session.CONTINUE` with a key, which is the case sessions
exist for: an agent on its fourth attempt remembering the three that failed.

## `cover_diff` — close the coverage gap on this branch

```bash
vekna cast cover_diff --bound 3
```

Takes `diff-cover`'s report of changed-but-untested lines and works them down,
with a rule per layer: uncovered lines in `gates` want an integration test,
uncovered lines in `mills` want a unit test, and dead code is a question for
you rather than a thing to test.

Its agent runs with `gate_tools=["Bash"]`, so every command it wants to
run is put to you first.

**Credentials:** none.

## `sweep`, `ci_watch`, `pr_fix` — keep every pull request green

```bash
vekna cast sweep --max-prs 5
```

Three rituals, one cast each. `sweep` lists the open pull requests against the
base branch, queues a `ci_watch` for each with `enqueue`, and ends. `ci_watch`
reads one pull request's CI; red, it waits on a `pr_fix` with `await_cast`,
giving up its process slot meanwhile, then reads CI again. `pr_fix` checks the
branch out in a leased worktree, has an agent fix it, and asks you before it
pushes. How many run at once is `[circle]`'s answer. Cast by hand, `pr_fix`
runs in your own checkout and switches its branch; queue it to get a leased
tree.

`sweep` takes the base branch from `[defaults.sweep]`, and `pr_fix` its push
remote from `[defaults.pr_fix]` — an https one, since a cast has no terminal for
an ssh passphrase. `sweep` and `ci_watch` need the daemon. The terminal that
cast `sweep` follows every cast it queued, one at a time, and asks the push
there; claim it from the dashboard with `t` to answer it there instead. To run
the pull requests side by side, queue the sweep: `vekna cast --queue sweep`.

**Credentials:** a GitHub token that reads pull requests and CI runs, and a git
credential that pushes to this repository's branches.

Worth reading for the fence. The CI log and the diff are fenced as untrusted,
the agent runs under `dontAsk` with an allowlist — edits, `mise run`, `git add`
and `commit`, reading CI — and pushing stays with the ritual, behind your
answer. `mise run` still runs tasks the branch defines, so `sweep` queues no
pull request from a fork.

## Writing your own

Start from [Rituals](rituals.md), and keep one file until it earns a package.
When it does, split by ritual — `triage.py` and `review.py` — because a ritual
is the unit anyone reads. Once a ritual outgrows its own file, or rituals share
prompts, commands or state,
[split by role](#when-one-ritual-outgrows-its-file).

Then [test it](testing.md). A ritual with no test is a program whose only
check is running it against a live agent.

Writing one with Claude Code? Install the
[`ritual-scribe`](https://github.com/fancysnake/vekna/blob/main/plugins/ritual-scribe/skills/ritual-scribe/SKILL.md)
plugin:

```bash
claude plugin marketplace add fancysnake/vekna
claude plugin install ritual-scribe@vekna
```

It carries the shipped surface — every decorator, every medium argument, and
the things that are planned but not yet bound, quarantined so the agent does
not write against them. An agent guessing at this API writes something that
reads correctly and does not run.

### When one ritual outgrows its file

Split the package by role, and let its rituals share the role modules.
cabinet's
[`heal`](https://github.com/fancysnake/cabinet/blob/v7.3.0/src/cabinet/rituals/heal_mine.py)
rituals are the worked case:

| role | what it holds |
| --- | --- |
| entry | the `@ritual` functions, one file per ritual |
| steps | the `@step` bodies, one module per task: `merge`, `ci`, `answer`, `review` |
| prompts | every prompt a step sends, for these rituals and the others |
| commands | every git command a step runs |
| state | the components and payload models |

A step module then reads as routing: which payload comes in, what the step
checks, where it goes next. The wording of a prompt and the flags of a command
change without the graph changing, so they change in a file of their own.
Split the steps again by task once they outgrow one module; the graph still
reads top to bottom inside each.

### What a payload shared by every step costs

Prefer one payload model per shape: a field two steps need travels in each
step's own model. Sometimes every step needs the same state. `heal` owes its
report however the cast ends, so every step carries the run. One model threaded
through every step has two costs, and both are code you write by hand.

**A class per step.** A payload class belongs to one step, so the shared model
gets one empty subclass per step.

**A rebuild per hop.** Each hop builds the next step's class from the fields of
the last. Pass them as keyword arguments:

```python
class Run(BaseModel):
    queue: list[int] = []
    stopped: str = ""


class Survey(Run):
    pass


class Report(Run):
    pass


@step
async def survey(state: Survey) -> Report:
    return Report(queue=state.queue, stopped="the forge refused the token")
```

A type checker rejects a misspelled keyword. The price is that every hop lists
every field it carries, and a field you leave out silently takes its default.

For a model with many fields, list them once instead, in a copy method on the
shared model: one optional keyword argument per field a step may change, passed
on to `model_copy`. Do not call `model_copy(update=...)` from a step: it takes
an untyped mapping, so a misspelled field passes the type checker and pydantic
alike. The copy keeps its class, so a second method re-tags it as the next
step's with `kind.model_validate_json(self.model_dump_json())`. The trip through
JSON returns exactly `kind`, and avoids the `dict[str, Any]` of `model_dump()`,
which mypy's `disallow_any_expr` rejects.

Each field appears three times in such a copy method, and cabinet's two shared
models cost about forty such lines between them. vekna ships no helper for this:
no generic copy method on a base class gets a typed signature per field.
Whether a step could instead be routed to by name, with no class of its own, is
undecided: see [#221](https://github.com/fancysnake/vekna/issues/221). Pay
these costs only when the state really is shared.
