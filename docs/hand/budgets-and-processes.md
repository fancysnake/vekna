# A long-running thing: what it spends, and how it ends

See [`../reborn/common.md`](../reborn/common.md) — loop safety, Components,
telemetry in the grimoire — and [`../reborn/locks.md`](../reborn/locks.md),
whose `system:claude-quota` is the neighbouring tool.

Two halves of the same question, filed together because a folio that owns a
process wants the ceiling before it wants the folio. A budget caps what a cast
consumes; `folio/process` owns what a spawned thing costs to keep alive and how
it is torn down.

## Cast budgets: wall time and tokens

`max_steps` and `max_visits` bound the *graph*. Neither bounds cost. A ritual
that loops on a coding rite can spend a day of quota well inside its step
budget, and the first anyone knows is the bill or the rate limit.

The meter already exists — per-call telemetry (session, tool calls, tokens)
rides `RiteFinished.result` and lands in the journal. This is the ceiling to go
with it.

- **`@ritual(max_duration=..., max_tokens=...)`** — beside the `max_steps` that
  is already there. Exceeding either raises `CastBudgetExceededError`, a sibling
  of `StepBudgetExceededError`.
- **It arrives as a `Failure`**
  ([failure-as-transition.md](failure-as-transition.md)), so a ritual
  can catch it and `done` with a partial report rather than dying with the work
  unaccounted for. A migration babysitter that runs out of budget should say
  which files it converted. The overrun surfaces at the *next* step boundary,
  not inside the step that spent the budget — so the `Failure` reaches the step
  that was about to start, carrying the payload it was entered with.
- **Read at step boundaries.** Determinism lives at the step boundary, so that
  is where the meter reads: on entry to each step, before the input validation.
  A single rite that overruns the whole budget by itself is
  [bounding-a-rite.md](bounding-a-rite.md)'s job, not this one — a budget that
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

### Budgets and locks are different tools

`lock("system:claude-quota")` serialises access: one cast at a time reaches the
provider. A budget caps consumption: this cast gets this much. They compose —
the lock stops two casts racing for the same quota, the budget stops one cast
eating all of it — and neither substitutes for the other. A pooled budget shared
*across* casts is a lock's problem and stays out of scope here.

## `folio/process`

What this folio is actually about is lifetime: spawn, wait, signal, kill, and a
child that does not outlive the cast that started it. That is cancellation
reaching the process ([bounding-a-rite.md](bounding-a-rite.md)) plus a bound on
what a running thing may spend — build it without them and it needs a second,
private teardown mechanism that later gets rewritten. `folio/shell`'s `run_bash`
already carries that debt: no timeout, no output cap, and a child reaped only on
the success path.

Land the dev-server use case. Process and Executable are **Mediums, not
values**: lifetime concerns live in the folio, not the ritual body. Treating a
running process as a plain Component value would leak lifetime (spawn, wait,
kill) into ritual code.

- `vekna.folio.process` — `spawn` and `attach` Mediums. The folio owns process
  lifetime.
- Value-typed Components `Pid`, `ExecutableSpec` stay in the lexicon's component
  surface; only `Process`/`Executable` lifetime moves into the folio.
- A worked example exercising the dev-server pattern (start a server, get a
  PID/handle, run rites against it, tear down).

## Scope

- `lexicon/_specs.py` — defaults, config keys, duration parsing.
- `lexicon/_pacts.py` — `CastBudgetExceededError`, the budget state model.
- `lexicon/_mills/` — the meter, read at the step boundary; token accumulation
  from `RiteFinished.result`.
- `wire/_pacts.py` — budget consumption on the cast state message.
- Daemon `mills/` + `gates/cli/click/` — the 80% warning, the `vekna casts`
  column.
- `vekna.folio.process/{_pacts,_mills,_links,_gates}.py` + `register`;
  `_links.py` owns subprocess lifetime (spawn/wait/signal/kill); an
  import-linter contract for the new folio (lexicon public + wire only).

## Out of scope

Cost in currency. Tokens are what the Focus reports; a pricing table would go
stale in a month and belongs to whoever is paying the bill. Per-Focus budgets in
one cast — that is multi-Focus territory, which stays on
[`../reborn/common.md`](../reborn/common.md)'s not-planned
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
- A ritual spawns a long-running process, runs rites against it, and tears it
  down cleanly on cast exit — no orphaned processes.
- A typed handle returns validated (`output=ServerHandle` style).
- `mise run fullcheck` passes.
