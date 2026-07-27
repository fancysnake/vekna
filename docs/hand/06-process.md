# Feature — `folio/process`

**Version:** `3.0.0`

See [`../reborn/00-common.md`](../reborn/00-common.md) — Components (deferred
Process/Executable).

Filed under Reborn as `0.4.0` until July 2026, and moved here because what this
folio is actually about is lifetime: spawn, wait, signal, kill, and a child that
does not outlive the cast that started it. That is cancellation reaching the
process ([02-timeout-race.md](02-timeout-race.md)) plus a bound on what a
running thing may spend ([03-budgets.md](03-budgets.md)) — both already Hand's,
and both wanted *before* a folio whose whole job is owning a process. Landing
this first would have meant writing a second, private teardown mechanism and
then rewriting it. `folio/shell`'s `run_bash` already carries that debt: no
timeout, no output cap, and a child reaped only on the success path.

## Goal

Land the dev-server use case. Process and Executable are **Mediums, not
values**: lifetime concerns live in the folio, not the ritual body. Treating a
running process as a plain Component value would leak lifetime (spawn, wait,
kill) into ritual code.

## What ships

- `vekna.folio.process` — `spawn` and `attach` Mediums. The folio owns process
  lifetime.
- Value-typed Components `Pid`, `ExecutableSpec` stay in the lexicon's
  component surface; only `Process`/`Executable` lifetime moves into the folio.
- A worked example exercising the dev-server pattern (start a server, get a
  PID/handle, run rites against it, tear down).

## Scope

- `vekna.folio.process/{_pacts,_mills,_links,_gates}.py` + `register`.
- `_links.py` owns subprocess lifetime (spawn/wait/signal/kill).
- Import-linter contract for the new folio (imports lexicon public + wire only).

## Out of scope

Vekna daemon. Locks. TUI.

## Acceptance

- A ritual spawns a long-running process, runs rites against it, and tears it
  down cleanly on cast exit — no orphaned processes.
- Typed handle returns validate (`output=ServerHandle` style).
- `mise run check` and `mise run test` pass.
