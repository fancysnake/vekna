# Current Task

**Task:** Feature 0.3.0 — `folio/coding` + `folio/coding_claude`
**Spec:** `docs/reborn/03-coding-folios.md`
**Plan:** not yet written (Explore done; Plan awaits approval)
**Branch:** `vekna-reborn`
**Phase:** EXPLORE complete — findings reported, awaiting plan go-ahead

## Context

0.2.0 shipped and released (2026-06-28). Docs reconciled to the step-graph
model and decide-only prompts (commit `fc30588`). Product direction: daily dev
workflows (PR triage, merge babysitting) as rituals — 0.3.0's `coding` medium
is the last missing primitive for those.

## Exploration findings (2026-07-18)

- **Decide consolidation is step 0.** Code still ships `approve`/`ask`:
  `Channel` protocol (`lexicon/_pacts.py`), `StandaloneRenderer`
  (`lexicon/_links.py`), `folio/flow/_mills.py`, and `Approval*`/`Ask*` DTOs in
  `wire/_pacts.py`. Docs now say `decide` is the single human round-trip.
  Unified `decide` signature is an open design decision.
- **Shell folio is the template** for `folio/coding` (`_pacts` result model,
  `_mills` medium, `_links` side effects). `@medium` wrapper + `RiteContext`/
  `Channel` machinery already exist.
- **No focus registry exists.** Compendium registers rituals only. `coding`
  needs a way to resolve its Focus, plus `try/except ModuleNotFoundError` for
  the missing `coding-claude` extra.
- **Telemetry path:** `Grimoire` emits only `RiteStarted`/`RiteFinished`;
  `RiteDelta` exists in wire but is unused — needed for streamed agent output
  + telemetry in the grimoire entry.
- **CLI dispatch pattern:** gates never import lexicon; `inits/cast.py`
  `dispatch_cast` dynamically imports `vekna.lexicon.main(argv)`. `rituals
  list/show` and the `vekna cast "<prompt>"` sugar must ride the same shim.
  `_gates.py --help` already lists rituals + flags (basis for `rituals list`).
- **pyproject changes required** (need per-case approval): `coding-claude`
  extra with optional `claude-agent-sdk` dep; two new import-linter contracts
  (`folio.coding`, `folio.coding_claude`).
- **Owed from 0.2.0:** `parallel` deferred (TUI spec assumes it from 0.2.0);
  not a 0.3.0 blocker. Wire client deferred to 0.6.0 by design.

## Open decisions needing human input

1. Unified `decide` signature (choice / confirmation / free text in one
   medium — modes? return type? docs example uses bare
   `await decide("tests green — commit?")` as truthy).
2. `vekna cast <arg>` disambiguation: ritual name vs prompt sugar.
3. Focus-registry shape (how `coding` finds `ClaudeCodingFocus`; how a missing
   extra surfaces).
4. Approval to modify `pyproject.toml` (extra + contracts) during
   implementation.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` for all verification (mise-managed env).
