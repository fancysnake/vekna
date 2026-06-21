# Current Task

**Task:** Feature 0.2.0 — Lexicon SDK + standalone runner
**Spec:** `docs/reborn/02-lexicon-standalone.md`
**Plan:** `PLAN.md`
**Branch:** `reborn`
**Phase:** COMPLETE — all 8 steps delivered; acceptance verified

## Status

- [x] Explore — feature spec, common.md, current src/test layout, import-linter
      contracts reviewed.
- [x] Retire tbd-* commands + TDD workflow section (commit `7f69bc8`).
- [x] **Plan approved**
- [x] Step 1 — `vekna.wire` (DTOs + framing) — commit `e4ea50e`
- [x] Step 2 — `vekna.lexicon` errors + components + skeleton — commit `d995bf1`
      (transitions/protocols/_specs moved to Step 3; Email deferred)
- [x] Step 3a — transitions + `@step` + `_dispatch` (mypy override) — commit `c9450fa`
- [x] Step 3b — `@ritual` + Grimoire + Compendium + engine + budget — commit `f752d4a`
- [x] Step 4 — links: probe + standalone renderer — commit `25e32bf`
      (wire client deferred to 0.6.0)
- [x] Step 5a — `vekna cast` runner + `inits` dispatch — commit `8d64972`
- [x] Step 5b — `.vekna.toml` config (tomli) — commit `8f675b5`
- [x] Step 6a — medium machinery (`@medium`, `RiteContext`, `Channel`) — commit `6c187f4`
- [x] Step 6b — `folio.flow` (`decide`/`approve`/`ask`) — commit `67a54a8`
      (`parallel` deferred)
- [x] Step 7 — `folio.shell` (shell medium + bash focus) — commit `221e3e4`
- [x] Step 8 — `fix_demo` example + acceptance — commit `d465502`

## Acceptance (all verified)

- [x] `vekna cast fix_demo --bound 3` runs end-to-end, structured Grimoire to
      stdout, exits 0.
- [x] `decide`/`approve`/`ask` prompt on stdin and route the answer back.
- [x] Probing the absent daemon socket is silent and does not hang.
- [x] `mise run check` and `mise run test` pass (165 passed; 12 contracts).

## Resolved design decisions (see PLAN.md "Key design decisions")

1. Dispatch lives in `inits/cli.py:run()` via dynamic `importlib` — `gates`
   never reference lexicon (option A). Cast runtime is `vekna.lexicon.main`.
2. `cast` loads `rituals.py` **in-process** via `importlib`; no ritual
   subprocess. Per-invocation OS process = the cast process.
3. `rituals.py` is self-sufficient/lintable; runner injects nothing;
   `lexicon`/`folio` `__init__` are the typed public surface; decorators are
   typing-transparent.
4. **Workflow model** (reshaped — see `00-common.md` "Ritual model"):
   `@ritual` = entrypoint (CLI Component interface + opening transition, not a
   step); `@step` = task taking a typed value, returning a `Transition`;
   `goto(step, payload)` / `done(result)` route by **returned value**, target
   by **direct function reference**; the step engine trampolines + validates
   input/output payloads at each boundary. Step payloads are defined Pydantic
   value types, not `Annotated` markers. `branch`/`repeat`/`attempt` fold into
   `goto`/guards/`try-except`; `folio/flow` = `decide` + `parallel`.
   Annotation-gated dispatch deferred.
5. **Loop safety (0.2.0):** trampoline is bounded — `@ritual(max_steps=N)`
   (total hops, `DEFAULT_MAX_STEPS` default) + optional `@step(max_visits=N)`;
   exceeding raises `WorkflowBudgetExceededError`. Distinct from business bounds
   (a step's own `budget`).
6. **Inferable graph (foundation now, render later):** static workflow graph is
   derivable from step I/O types (edge `A→B` when A's output payload type fits
   B's input; `done(T)` terminal). For `vekna eye` / `vekna rituals show`
   visualization. 0.2.0 only keeps the registry's I/O type info; inference +
   rendering land at 0.3.0/dashboard.

## Spec docs updated (uncommitted, awaiting review)

`docs/reborn/00-common.md` and `02-lexicon-standalone.md` rewritten to the new
model (vocabulary, Ritual-model section, lifecycle, Components note, flow-folio
scope, out-of-scope). Not committed — for human review.

## Open decisions needing human input

1. Config-file approvals are requested **per step** (import-linter contracts;
   `tomli` dep vs. raising Python floor to 3.11 at Step 5).

## Notes

- Stay on `reborn`; commit after each green step.
- `goal.md` is open in the IDE but not on disk — ignore unless it appears.
