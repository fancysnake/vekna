# Feature — Lexicon SDK + standalone runner

**Version:** `0.2.0`

See [00-common.md](00-common.md) for vocabulary, package layout, wire schema,
standalone mode.

## Goal

Ship the rituals SDK as a working program **without** the daemon and
**without** any agent provider. A user installs the package, writes
`rituals.py` using `folio/shell` + `folio/flow`, runs `vekna cast my_workflow`,
and gets a structured terminal experience. Proves the lexicon, the Grimoire,
the flow mediums, and the standalone renderer in isolation before any daemon or
agent work.

## What ships

- `vekna.lexicon` — `@ritual`, `@medium`, `RiteParams`, `RiteResult`,
  `RiteContext`, the Grimoire event log, the compendium registry.
- `vekna.wire` — Pydantic wire DTOs + framing helpers (versioned
  independently). The single schema home; daemon-side handlers land at 0.6.0.
- `vekna.lexicon._links` — wire client + probe loop (probes the Unix socket,
  falls back to standalone if unreachable) and the standalone renderer
  (stdout events; stdin prompts for `decide`/`approve`/`ask`). Probe degrades
  gracefully when the socket is absent.
- `vekna.folio.flow` — `decide`, `repeat`, `branch`, `attempt`, `parallel`.
- `vekna.folio.shell` — `shell` Medium + bash Focus.
- Worked example `examples/rituals.py`: at least one ritual using `shell` +
  `decide` + `repeat`.

## Scope

- New top-level packages `vekna.lexicon`, `vekna.wire`, `vekna.folio` with
  their own import-linter contracts (see common: core ⊥ lexicon/folio; folios
  ⊥ folios; folios → lexicon public + wire).
- Pydantic DTOs for the wire schema in `vekna.wire`. Probe degrades gracefully
  when the socket is absent.
- Unit tests for flow mediums; integration test for the standalone runner
  driving a small cast end-to-end.

## Out of scope

The daemon. Coding medium. Claude. TUI. Persistence. Locks (0.5.0).
`vekna cast "<prompt>"` sugar (0.3.0).

## Acceptance

- `vekna cast fix_demo --bound 3` runs end-to-end, prints a structured Grimoire
  to stdout, exits 0.
- `decide` / `approve` / `ask` prompt on stdin and route the answer back.
- Probing the absent daemon socket is silent and does not hang.
- `mise run check` and `mise run test` pass.
