# PLAN — lexicon refactor: shrink to the SDK, satisfy the new contracts

Source: the rewritten `[tool.importlinter]` contracts (2026-07-26) and the two
they break. Target shape: `docs/reborn/00-common.md:158-206`.

## Outcome

`vekna.lexicon` contains what a `rituals.py` or a folio imports, and the cast
runtime they need — nothing else. Everything CLI-shaped moves to the root
project. `mise run il` goes green without relaxing a single new rule.

## The rules, as rewritten

Derived from the forbidden lists; the same shape applies at root, in
`lexicon/_*`, and in each `folio/*/_*`:

| layer | may import |
| --- | --- |
| `pacts`, `specs`, `edges` | nothing internal |
| `mills` | `pacts`, `specs`, own submodules |
| `links`, `gates` | `pacts` |
| `inits` | everything except `edges`, `folio`, `lexicon` |

Root additionally carries `inside-*` independence contracts, so a root layer's
submodules may not import each other. Lexicon has no `inside-lexicon-*`
contract, so `lexicon/_mills` may be a package whose submodules cooperate —
verified, and Step 3 depends on it.

Two consequences drive this plan:

1. **No root module may import `lexicon`.** Not `gates`, not `inits`. So root
   cannot name a `Ritual` or a `Step`, and the CLI cannot call `run_cast`.
2. **`inits` is the only binding layer.** `lexicon-inits` forbids only
   `_edges`, so `lexicon/_inits.py` may import every other lexicon layer. That
   is where the cast runtime's wiring belongs.

## Approved decisions

1. **Gates are pacts-only** — confirmed. Everything binds in `inits`.
2. **`vekna.wire` stays unconstrained** — confirmed, revisit at 0.6.0.
3. **Root reaches the cast runtime by dynamic import.** One `importlib` call in
   root `inits`, which is the mechanism the contracts require and what
   `inits/cast.py` did before Step 10 deleted it. Static imports cannot express
   this without breaking rule 1.
4. **The CLI never sees a ritual object.** Lexicon exposes string-returning
   entry points (`list_text()`, `show_text(name)`, `cast(argv)`); root's CLI
   parses argv, calls one of them, prints, exits. This is what keeps rule 1
   satisfiable without moving ritual types to root.

---

## Step 1 — Delete what nothing imports

Pure subtraction, no moves. Establishes the real surface before anything is
rearranged.

- **`entry.py` — delete.** It exports nine names. Six (`run_cast`,
  `Compendium`, `Grimoire`, `StandaloneRenderer`, `probe_daemon`,
  `default_socket_path`) have no consumer anywhere in `src/`, `tests/` or
  `rituals.py`. The other three are re-exports for one importer.
  `inits/cli.py` imports `vekna.lexicon._gates` directly until Step 4 moves it.
- **`reset_foci` — remove from the public API.** Used only by tests. The
  registry keeps a reset; tests reach it as a private seam rather than the
  ritual author's door advertising a test hook.
- **`Channel.emit` — delete.** Dead since it was written; its own comment says
  so. `StandaloneRenderer.emit` goes with it.

**Verify.** `mise run test && mise run check`. `vekna.lexicon.__all__` drops
from 29 to 28; `entry.py` and its 9-name surface are gone.

## Step 2 — Move the standalone surface out of lexicon

Nothing in `lexicon` or `folio` imports these; only the CLI path does.

- `_links.py` (`StandaloneRenderer`, `probe_daemon`, `default_socket_path`)
  → `vekna/links/`. Root `links` may import root `pacts` only — and it needs
  `WireMessage`, which is `vekna.wire`, unconstrained. Clean.
- `Channel` moves to root `pacts` **only if** nothing in folio needs it.
  `folio/coding/_mills.py` imports `Channel`, so it **stays** in
  `lexicon/_pacts.py` and root `links` depends on `vekna.wire` alone.

**Verify.** `mise run il` — the `links` contract stays KEPT. `mise run test`.

## Step 3 — Give the unlayered modules a layer

The actual structural mess: `_dispatch.py`, `_graph.py`, `_loader.py`,
`components.py` and `entry.py` are five of lexicon's ten modules and are exempt
from every contract purely because their names do not match a layer. That is
how `_gates` was reaching `_mills` — through `_dispatch`, `_graph` and
`_loader`, which import-linter only caught as a transitive chain.

- `components.py` → `_pacts` (public component types; imports nothing internal).
- `_graph.py` → `_mills` (pure AST logic over `Ritual`).
- `_loader.py` → `_links` (file import, TOML read — I/O).
  Requires the split below: `_loader` returns loaded `Ritual`/`Step` objects
  and `_inits` registers them, so `_links` needs `_pacts` only.
- `_dispatch.py` → `_mills`. Lexicon has **no** `inside-lexicon-mills`
  independence contract, so `_mills` may become a package whose submodules
  cooperate. This keeps `_dispatch`'s mypy `disallow_any_expr` exemption
  scoped to one submodule instead of spreading it to the engine, and lets it
  keep reading `DEFAULT_MAX_STEPS` from `_specs` directly (`mills → specs` is
  permitted).

Proposed shape:

```
lexicon/
  _pacts.py      # contracts + component types
  _specs.py      # (pending the open question)
  _mills/        # __init__.py, engine.py, grimoire.py, compendium.py,
                 # registry.py, dispatch.py, graph.py
  _links.py      # ritual file / module / TOML loading
  _inits.py      # the binding layer: folio loading, cast runtime, CLI texts
```

**Verify.** `mise run il` — `lexicon-*` all KEPT, including `lexicon-gates`
(there is no longer a `_gates` in lexicon). `mise run test`.

## Step 4 — Move the CLI to the root project

- `lexicon/_gates.py` **dies**. Its argv parsing and help/list/show formatting
  go to `vekna/gates/cli/click/`; its ritual-typed work (`_build_compendium`,
  `_drive`) goes to `lexicon/_inits.py` behind the three string-returning entry
  points from decision 4.
- `vekna/inits/cli.py` keeps the click tree and gains the single dynamic import
  of `vekna.lexicon._inits`. Root `gates` stays pacts-only; root `inits` binds.

**Verify.** `mise run il` — 31 kept, 0 broken, with **no rule relaxed**. Then
confirm the contracts still bite: reintroduce a static
`from vekna.lexicon import ...` in root `inits` and see `inits` break.

## Step 5 — Reconcile

`docs/architecture.md` (the layer table now says gates are pacts-only; the
layout section), `CLAUDE.md` if its layer list disagrees, `CHANGELOG.md`,
`CURRENT_TASK.md`. `00-common.md:211-213` also needs the correction agreed
earlier — the "only place either side imports from" sentence.

---

## Not in scope

- The **grimoire-vs-wire coupling** (lexicon's event model *is* the transport
  schema). Discussed, still open, deliberately not bundled — it touches the
  same files and would make this unreviewable.
- Restoring a `wire` contract — decided against for now.
- The five P3s carried in `CURRENT_TASK.md`.
