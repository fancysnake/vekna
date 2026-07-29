# Feature — `timeout` and `race`

**Version:** Hand (`3.x`), unscheduled within it.

See [`../reborn/02-lexicon-standalone.md`](../reborn/02-lexicon-standalone.md)
— `folio/flow` — and [01-failure.md](01-failure.md), which is where a timeout
lands.

## Goal

Nothing in vekna bounds a single rite. `max_steps` bounds transitions and
`max_visits` bounds re-entry; neither is a clock. An agent rite that stops
making progress hangs the cast, the daemon shows it running, and it shows it
running all night.

`folio/flow` ships `decide` and nothing else. `timeout` and `race` are the two
primitives it is missing, and they are cheap. (`parallel` was filed alongside
them once and dropped: concurrency inside a step body is plain `asyncio`, and
steps never run concurrently. See
[`../reborn/02-lexicon-standalone.md`](../reborn/02-lexicon-standalone.md).)

## What ships

- **`timeout`** — bounds any awaitable inside a step body:

  ```python
  from vekna.folio.flow import timeout, race

  result = await timeout(coding(prompt="..."), seconds=600)
  ```

- **`@step(timeout=...)`** — the same ceiling over a whole step, for the common
  case where the step *is* one long rite. The medium is the primitive; the
  decorator argument is sugar over it.
- **A timeout is a `Failure`.** `RiteTimeout` raises, so a step with `on_error`
  routes to recovery and one without aborts the cast — the "convert" case from
  01. There is no separate timeout-handling mechanism, and nothing new to learn
  to catch one.
- **`race`** — first to finish wins, the rest are cancelled:

  ```python
  winner = await race(coding(prompt=fast_path), coding(prompt=thorough))
  ```

  Losers are recorded in the grimoire as cancelled, with what they had produced
  when the winner landed. A rite that vanishes from the tree because something
  else finished first is a rite the operator cannot account for.
- **Cancellation reaches the process.** This is the part with actual work in it.
  A cancelled `shell` rite kills its subprocess and its children; a cancelled
  `coding` rite interrupts the SDK session rather than abandoning it.
  Propagation across an `asyncio.TaskGroup` in a step body is Python's own, so
  what vekna owes is per-medium cancellation, not a fan-out story. A timeout
  that returns
  promptly while leaving a `claude` process chewing through the repo is worse
  than no timeout at all, because it lies to the operator and to the lock
  manager.
- **`RiteCancelled`** on the wire, so the daemon and the Eye can draw the
  difference between finished, failed, and cancelled.
- Foci declare whether they are interruptible. One that is not gets no
  `timeout` support and says so at the call, rather than accepting the argument
  and quietly ignoring it.

## Scope

- `folio/flow/{_pacts,_mills}.py` — `timeout`, `race`, `RiteTimeout`.
- `lexicon/_mills/` — the `timeout=` step argument, applied at the same
  boundary the input validation is.
- `folio/shell/_links.py` — process-group kill on cancel.
- `folio/coding_claude/_links.py` — session interrupt on cancel.
- `wire/_pacts.py` — `RiteCancelled`.

## Out of scope

A cast-wide deadline inherited by every step — that is a budget, and it lives in
[03-budgets.md](03-budgets.md). Retry and backoff — that is recovery, and it
lives in [01-failure.md](01-failure.md). Timeouts on the daemon's own
operations; the daemon is not the thing that hangs.

## Acceptance

- A `coding` rite exceeding its `timeout` raises `RiteTimeout`, and a step with
  `on_error` recovers from it like any other failure.
- After a timeout, no agent subprocess survives: the process group is gone and
  the SDK session is closed. Verified by inspecting the process table, not by
  trusting the return.
- `race` returns the first result, marks the losers cancelled in the grimoire,
  and leaves nothing running.
- A `timeout` around an `asyncio.TaskGroup` in a step body cancels every task in
  it, and each cancelled rite reaches its own process.
- A Focus that cannot be interrupted rejects `timeout=` at the call with a clear
  message rather than accepting it silently.
- A cast whose only rite times out exits non-zero with the rite named, not with
  a bare `CancelledError` traceback.
- `mise run check` and `mise run test` pass.
