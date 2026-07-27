# Feature — Lexicon SDK + standalone runner

**Version:** `0.2.0`

See [00-common.md](00-common.md) for vocabulary, package layout, wire schema,
standalone mode.

## Goal

Ship the rituals SDK as a working program **without** the daemon and
**without** any agent provider. A user installs the package, writes
`rituals.py` — a `@ritual` entrypoint plus `@step` tasks wired by `goto`/`done`,
using `folio/shell` + `folio/flow` — runs `vekna cast my_workflow`, and gets a
structured terminal experience. Proves the lexicon (entrypoint + step graph +
transition trampoline + boundary type enforcement), the Grimoire, the flow
mediums, and the standalone renderer in isolation before any daemon or agent
work.

## What ships

- `vekna.lexicon` — `@ritual` (entrypoint, `max_steps`), `@step` (task),
  `goto`/`done`/`Transition` (routing), `@medium`, the step engine (transition
  trampoline + on-entry input type enforcement + bounded loop-budget guard
  raising `StepBudgetExceededError`), the Grimoire event log, the compendium
  registry. `RiteContext` is engine-internal, not user-facing (lands with the
  flow/coding folios). (Static graph-inference + rendering deferred to
  `rituals show`/the dashboard, derived from `goto` targets + step input types.)
- `vekna.wire` — Pydantic wire DTOs + framing helpers (versioned
  independently). The single schema home; daemon-side handlers land at 0.6.0.
- `vekna.lexicon._links` — wire client + probe loop (probes the Unix socket,
  falls back to standalone if unreachable) and the standalone renderer
  (stdout events; stdin prompts for `decide`). Probe degrades
  gracefully when the socket is absent.
- `vekna.folio.flow` — `decide` (the single human round-trip: choice,
  confirmation, free text) + `parallel`. `branch`/`repeat`
  fold into conditional `goto` / `goto`-with-guard at the step level, and
  `attempt` into ordinary `try/except` in a step body — not separate mediums.
- `vekna.folio.shell` — `shell` Medium + bash Focus.
- Worked example: a `@ritual` with at least two `@step`s wired by
  `goto`/`done`, using `shell` + `decide` and a guarded loop. Since 0.3.0 this
  is `rituals.py` at the repo root — vekna's own rituals, cast on itself.

## Scope

- New top-level packages `vekna.lexicon`, `vekna.wire`, `vekna.folio` with
  their own import-linter contracts (see common: core ⊥ lexicon/folio; folios
  ⊥ folios; folios → lexicon public + wire).
- Pydantic DTOs for the wire schema in `vekna.wire`. Probe degrades gracefully
  when the socket is absent.
- Unit tests for the step engine (transition trampoline + boundary type
  enforcement) and the flow mediums; integration test for the standalone runner
  driving a small cast end-to-end.

## Out of scope

The daemon. Coding medium. Claude. TUI. Persistence. Locks (0.5.0).
`vekna cast "<prompt>"` sugar (0.3.0). Annotation-gated step dispatch
(`goto(payload)` without a named target) — explicit `goto(step, payload)` only
for now.

## Acceptance

- `vekna cast fix_demo --bound 3` runs end-to-end, prints a structured Grimoire
  to stdout, exits 0.
- `decide` prompts on stdin and routes the answer back.
- Probing the absent daemon socket is silent and does not hang.
- `mise run check` and `mise run test` pass.
