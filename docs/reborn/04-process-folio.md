# Feature — `folio/process`

**Version:** `0.4.0`

See [00-common.md](00-common.md) — Components (deferred Process/Executable).

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
