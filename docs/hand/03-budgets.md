# Feature — Cast budgets: wall time and tokens

**Version:** Hand (`3.x`), unscheduled within it.

See [`../reborn/00-common.md`](../reborn/00-common.md) — loop safety,
telemetry in the grimoire — and
[`../reborn/05-locks.md`](../reborn/05-locks.md), whose `system:claude-quota`
is the neighbouring tool.

## Goal

`max_steps` and `max_visits` bound the *graph*. Neither bounds cost. A ritual
that loops on a coding rite can spend a day of quota well inside its step
budget, and the first anyone knows is the bill or the rate limit.

The meter already exists — per-call telemetry (session, tool calls, tokens)
rides `RiteFinished.result` and lands in the journal. This is the ceiling to go
with it.

## What ships

- **`@ritual(max_duration=..., max_tokens=...)`** — beside the `max_steps` that
  is already there. Exceeding either raises `CastBudgetExceededError`, a sibling
  of `StepBudgetExceededError`.
- **It arrives as a `Failure`** ([01-failure.md](01-failure.md)), so a ritual
  can catch it and `done` with a partial report rather than dying with the work
  unaccounted for. A migration babysitter that runs out of budget should say
  which files it converted. The overrun surfaces at the *next* step boundary,
  not inside the step that spent the budget — so the `Failure` reaches the step
  that was about to start, carrying the payload it was entered with.
- **Read at step boundaries.** Determinism lives at the step boundary, so that
  is where the meter reads: on entry to each step, before the input validation.
  A single rite that overruns the whole budget by itself is
  [02-timeout-race.md](02-timeout-race.md)'s job, not this one — a budget that
  tried to interrupt mid-rite would be a second cancellation mechanism with
  worse manners.
- **Both default to off**, set per ritual or in config:

  ```toml
  [budgets]
  max_duration = "4h"
  max_tokens   = 2_000_000
  ```

  Off by default because any number vekna picks is wrong for someone's
  overnight migration, and a ceiling that fires on a legitimate cast teaches the
  operator to raise it without reading it. The decorator wins over config; a
  ritual that knows its own shape can say so.
- **Consumption is visible while it runs, not after.** Tokens and elapsed ride
  the cast's state to the daemon, so `vekna casts` shows `1.2M/2.0M tokens ·
  38m/4h` and the Eye can draw it. A budget you can only check by exceeding it
  is an alarm, not an instrument.
- **The daemon warns before it fires** — one line at 80%, once, on whatever
  surface is attached, routed like any other attention. The point of a budget on
  an unattended cast is that you find out in time to decide.

## Budgets and locks are different tools

`lock("system:claude-quota")` serialises access: one cast at a time reaches the
provider. A budget caps consumption: this cast gets this much. They compose —
the lock stops two casts racing for the same quota, the budget stops one cast
eating all of it — and neither substitutes for the other. A pooled budget shared
*across* casts is a lock's problem and stays out of scope here.

## Scope

- `lexicon/_specs.py` — defaults, config keys, duration parsing.
- `lexicon/_pacts.py` — `CastBudgetExceededError`, the budget state model.
- `lexicon/_mills/` — the meter, read at the step boundary; token accumulation
  from `RiteFinished.result`.
- `wire/_pacts.py` — budget consumption on the cast state message.
- Daemon `mills/` + `gates/cli/click/` — the 80% warning, the `vekna casts`
  column.

## Out of scope

Cost in currency. Tokens are what the Focus reports; a pricing table would go
stale in a month and belongs to whoever is paying the bill. Per-Focus budgets in
one cast — that is multi-Focus territory, which stays on 00-common's not-planned
list. Budgets shared across casts (see above). Any budget that interrupts a rite
in flight.

## Acceptance

- A ritual exceeding `max_tokens` stops at the next step boundary with
  `CastBudgetExceededError`, and a step with `on_error` turns it into a partial
  report.
- The same for `max_duration`, with a cast that sleeps past it.
- With neither set, nothing changes and nothing is printed.
- `vekna casts` shows consumption against the ceiling for a running cast, and
  the 80% warning appears once, on the attached surface.
- A decorator argument overrides the config value; config applies to a ritual
  that declares neither.
- The journal records final consumption, so a finished cast can be asked what it
  cost.
- `mise run check` and `mise run test` pass.
