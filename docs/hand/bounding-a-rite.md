# Bounding a rite: cancellation, `timeout`, `race`

See [`../reborn/common.md`](../reborn/common.md) — loop safety, mediums, foci.

Nothing in vekna bounds a single rite. `max_steps` bounds transitions and
`max_visits` bounds re-entry; neither is a clock. An agent rite that stops making
progress hangs the cast, the daemon shows it running, and it shows it running
all night.

Three pieces, one story: cancellation is the mechanism, and a clock and a race
are the two things that fire it. Cancellation is where the actual work is —
`timeout` and `race` are small on top of it and worthless without it.

## Cancellation reaches the process

Cancelling a rite has to cancel the *work*, not just the coroutine waiting on
it. A cancellation that returns promptly while leaving a `claude` process
chewing through the repo is worse than none at all, because it lies to the
operator and to the lock manager. `folio/shell`'s `run_bash` carries that debt
today: a child is reaped only on the success path.

- **A cancelled `shell` rite kills its subprocess and its children**, by process
  group, and waits for them to be gone before the rite closes.
- **A cancelled `coding` rite interrupts the SDK session** rather than
  abandoning it.
- **`RiteCancelled`** on the wire and in the grimoire, so every surface can draw
  the difference between finished, failed, and cancelled. A rite that vanishes
  from the tree because something else cancelled it is a rite the operator
  cannot account for.
- **Foci declare whether they are interruptible.** One that is not says so at
  the call rather than accepting a cancellation and quietly ignoring it.

Propagation across an `asyncio.TaskGroup` in a step body is Python's own, so
what vekna owes is per-medium cancellation, not a fan-out story.

## `timeout`

- **`timeout`** in `folio/flow` — bounds any awaitable inside a step body:

  ```python
  from vekna.folio.flow import timeout

  result = await timeout(coding(prompt="..."), seconds=600)
  ```

- **`@step(timeout=...)`** — the same ceiling over a whole step, for the common
  case where the step *is* one long rite. The medium is the primitive; the
  decorator argument is sugar over it.
- **A timeout is a `Failure`.** `RiteTimeout` raises, so a step that declares a
  recovery route takes it and one that does not aborts the cast — the "convert"
  case in [failure-as-transition.md](failure-as-transition.md). There is no
  separate timeout-handling mechanism, and nothing new to learn to catch one.

## `race`

Two ways to do the same job, and the ritual wants whichever answers first — a
fast path against a thorough one, or the same prompt against two foci.

- **`race`** in `folio/flow` — first to finish wins, the rest are cancelled:

  ```python
  from vekna.folio.flow import race

  winner = await race(coding(prompt=fast_path), coding(prompt=thorough))
  ```

- **Losers are recorded in the grimoire as cancelled**, with what they had
  produced when the winner landed.

## Scope

- `folio/flow/{_pacts,_mills}.py` — `timeout`, `race`, `RiteTimeout`.
- `lexicon/_mills/` — the `timeout=` step argument, applied at the same boundary
  the input validation is.
- `folio/shell/_links.py` — process-group kill on cancel.
- `folio/coding_claude/_links.py` — session interrupt on cancel.
- `lexicon/_pacts.py` + `wire/_pacts.py` — `RiteCancelled`, and the
  interruptible declaration on the Focus protocols.

## Out of scope

A cast-wide deadline inherited by every step — that is a budget, and it lives in
[budgets-and-processes.md](budgets-and-processes.md). Retry and backoff — that
is recovery, and it lives in
[failure-as-transition.md](failure-as-transition.md). Timeouts on the daemon's
own operations; the daemon is not the thing that hangs. Racing whole steps:
steps never run concurrently, and a quorum or a first-N has not been asked for.

## Acceptance

- Cancelling a `shell` rite leaves no process behind: verified by inspecting the
  process table, not by trusting the return. Cancelling a `coding` rite closes
  the SDK session.
- Cancelling a `TaskGroup` in a step body cancels every task in it, and each
  cancelled rite reaches its own process.
- A cancelled rite appears as cancelled in the grimoire, with what it had
  produced when it was cut; a Focus that cannot be interrupted says so at the
  call.
- A `coding` rite exceeding its `timeout` raises `RiteTimeout`, and a step with
  a recovery route recovers from it like any other failure. After a timeout, no
  agent subprocess survives.
- A cast whose only rite times out exits non-zero with the rite named, not with
  a bare `CancelledError` traceback.
- `race` returns the first result, marks the losers cancelled, and leaves
  nothing running; a loser that raises before the winner lands does not fail the
  race.
- `mise run fullcheck` passes.
