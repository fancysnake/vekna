# Steps as DTOs

See [common.md](common.md) — ritual model, transitions, the bounded trampoline.

## The question it answers

**How does the engine know a ritual's edges without guessing?**

Today it guesses. `goto(target: Step, payload: BaseModel | None)` erases both
ends: nothing checks that `write_tests` accepts an `Uncovered`, because
`_checked` and `StepBoundaryError` are runtime, and the annotation carried by
`goto` says only `Step`. Type-checking a ritual file does not close this — the
erasure survives it. The graph is recovered by parsing each step's source for
`goto` calls whose first argument is a bare name, so a computed target is
invisible.

What that costs, measured on a real file:

```console
$ vekna rituals show merge_ready
steps:
  (start) → gates
  gates → repair, (done)
  repair → gates
```

Three edges for a step that runs an `asyncio.TaskGroup` over two shells, checks
green, checks a budget, classifies a failure three ways and asks a human. And
that is not an outlier: **17 of 24 steps** across the two real ritual sources
branch internally, one with five conditions and six exits.

## What ships

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
  still cannot call a step — a property that is structural here rather than
  conventional.
- `Done[T]` goes generic, so a ritual's result type is stated rather than
  `BaseModel | None`.

## Costs

- **Breaking change to the public surface.** `goto` goes and `Transition`
  changes shape. Cheapest before the API is fixed rather than after — this is
  the whole of what is left to decide about it.
- **One payload type per step identity** — two steps cannot share a payload
  shape. Already true of every step in the tree, so it costs nothing today.
- **`raise` exits stay outside the type.** Several steps raise `RitualError`,
  and no return annotation says so.

## Rejected, recorded so it is not rediscovered

**Declared edges.** `@step(goes_to=[...])` naming a step's successors, with the
engine cross-checking every actual transition and raising on an undeclared edge.
Cheap, additive, no API break — but the declaration is a second place to keep
right, it can drift from the body until a cast happens to walk the missed edge,
and it is verified at runtime on the path taken, so an edge never walked is
never checked. Rituals are inside mypy's scope, and a type-checked return
annotation is a superset of a runtime-cross-checked decorator argument, so this
loses outright.

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

It reads far better, deletes most of the per-step payload models, and turns
failure-as-a-transition into ordinary `try/except`. Rejected on one point: it
moves cast state from an externalized `(next step, payload)` pair into a Python
coroutine frame — loop counters and locals — which cannot be serialized. Resume
after a death would need replay-from-journal, Temporal-style, with determinism
enforced in ritual bodies rather than merely documented. That is a larger bet
than this project has a reason to make, and it trades a working resume for
readability.

Steps-as-DTOs keeps the trampoline and the single serializable cursor; it
changes only how the next step is *spelled*.

## Not the question

**Concurrency.** Steps never run concurrently. A transition is a sum — one
successor, chosen — and concurrency is a product, which is why it lives inside a
step body as plain `asyncio` and not in the graph at all.

## Acceptance

- Every ritual in the tree type-checks against its own declared exits, and a
  deliberately mis-wired `goto` fails `mise run check` rather than a cast.
- `Done[T]` carries the ritual's result type.
- `rituals show` draws the graph off the annotations, and a computed target is
  no longer a thing that can exist.
- `mise run fullcheck` passes.
