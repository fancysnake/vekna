# Feature — Steps as DTOs

**Version:** undecided. Competes with
[`../eye/04-graph.md`](../eye/04-graph.md); exactly one of the two should be
built.

See [00-common.md](00-common.md) — ritual model, transitions, the bounded
trampoline.

## The question both answer

**How does the engine know a ritual's edges without guessing?**

Today it guesses. `goto(target: Step, payload: BaseModel | None)` erases both
ends: nothing checks that `write_tests` accepts an `Uncovered`, because
`_checked` and `StepBoundaryError` are runtime, and the annotation carried by
`goto` says only `Step`. Type-checking a ritual file does not close this —
`SRC_PATHS` now covers `rituals.py` and the erasure survives it. The graph is
recovered by parsing each
step's source for `goto` calls whose first argument is a bare name, so a
computed target is invisible — `00-common.md` calls this inferable and
best-effort, and `04-graph.md` is blunter: *"drawing a graph you know is
incomplete is a weaker feature than not drawing one."*

What that costs, measured on the real file:

```console
$ vekna rituals show merge_ready
steps:
  (start) → gates
  gates → repair, (done)
  repair → gates
```

Three edges for a step that runs an `asyncio.TaskGroup` over two shells, checks
green, checks a budget, classifies a failure three ways and asks a human. And
that is not an outlier: **17 of 24 steps** across `rituals.py` and
`examples/pr_sweep.py` branch internally, `advance` with five conditions and six
exits.

## Option A — declared edges (`eye/04-graph.md`)

`@step(goes_to=[...])` names a step's successors; the engine cross-checks every
actual transition against the declaration and raises on an undeclared edge.

- Cheap, additive, **no API break**.
- The declaration is a second place to keep right, and it can drift from the
  body until a cast happens to walk the missed edge.
- Verified at runtime, on the path taken. An edge never walked is never checked.

## Option B — steps as DTOs (this doc)

A step returns the next step *as a value*, and its return type names the
alternatives:

```python
async def measure(state: Uncovered) -> WriteTests | Done[CoverReport]: ...
```

- **The return type is the declaration.** There is no second place, so nothing
  can drift.
- Verified statically, on every edge, walked or not. A mis-wire fails at
  type-check instead of mid-cast.
- A step's exits appear on hover. Today every step returns `Transition`, a union
  that tells a reader and an editor nothing.
- Step values stay **inert data**. Constructing one runs nothing, so a step
  still cannot call a step — the property `goes_to` asks authors to respect is
  structural here rather than conventional.
- `Done[T]` goes generic, so a ritual's result type is stated rather than
  `BaseModel | None`.

Costs:

- **Breaking change to the public surface.** `goto` goes and `Transition`
  changes shape. That is 1.0-shaped work, and it is cheapest before the API is
  fixed rather than after.
- **One payload type per step identity** — two steps cannot share a payload
  shape. Already true of every step in the tree (`Attempt`, `Red`, `Uncovered`,
  `Diff` are all distinct), so it costs nothing today.
- **`raise` exits stay outside the type**, the same blind spot Option A has.
  `collect` and `read_link` both raise `RitualError`; `sync_base` in the example
  raises three times.
- ~~**It buys nothing until rituals are type-checked.**~~ **Spent.** This was
  the cost that held B back, and it is paid: `SRC_PATHS` is `src rituals.py`,
  the `@step`/`@ritual` contravariance issue that blocked it is fixed, and
  `mypy` is clean on the file that used to report 22 errors. What B buys is now
  collectable the day it is built. See
  [10-ritual-modules.md](10-ritual-modules.md), Out of scope.

## What decides it

- ~~**If rituals never enter mypy's scope**, B is hover polish and A is the real
  answer.~~ Moot: they entered.
- **If they do**, B subsumes A completely and `goes_to` should not be built at
  all — a type-checked return annotation is a superset of a
  runtime-cross-checked decorator argument. **This is the branch that fired.**
- **Timing.** B breaks the public API. Deciding after 1.0 means either not doing
  it or holding it for 2.0; A can land any time.

The prerequisite was: fix the decorator generics, get rituals type-checked, and
the choice answers itself. Both halves landed together, so on this document's
own rule the *choice* is answered — B over A, and `04-graph.md`'s `goes_to`
should not be built. Only **timing** is still open, and it is the harder half:
B breaks the public API, so it is 1.0 work or it is 2.0 work, and nothing about
type-checking rituals decides which.

## Not the question

**Concurrency.** Steps never run concurrently under either option. A transition
is a sum — one successor, chosen — and concurrency is a product, which is why it
lives inside a step body as plain `asyncio` and not in the graph at all
([02-lexicon-standalone.md](02-lexicon-standalone.md)).

## Rejected, recorded so it is not rediscovered

**The imperative alternative** — the ritual holds the control flow and steps
return plain values:

```python
while budget > 0:
    report = await measure()
    if report.covered:
        return CoverReport(covered=True, remaining=budget)
    await write_tests(report)
    budget -= 1
```

It reads far better than either option above, deletes most of the per-step
payload models, and turns [`../hand/01-failure.md`](../hand/01-failure.md) into
ordinary `try/except`. It was rejected on one point: it moves cast state from an
externalized `(next step, payload)` pair into a Python coroutine frame — loop
counters and locals — which cannot be serialized. `vekna casts resume` after a
death ([07-lich.md](07-lich.md)) would need replay-from-journal, Temporal-style,
with determinism enforced in ritual bodies rather than merely documented. That
is a larger bet than this project has a reason to make, and it trades a working
resume for readability.

Option B keeps the trampoline and the single serializable cursor; it changes
only how the next step is *spelled*.

## Deciding

Not scheduled — but no longer blocked, and the blocker is not coming back. What
is left to decide is when, not which: see "What decides it" above. Record the
decision here when it is made, and delete the losing option from both this file
and `04-graph.md` rather than leaving two live designs for the same problem.
