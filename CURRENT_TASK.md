# Current Task

**Task:** lexicon refactor — shrink to the SDK, satisfy the new contracts
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete (commit `d09823e`)
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — awaiting review

## Context

The import contracts were rewritten to a strict per-layer model: every layer
imports only `pacts` (plus `specs` for mills), `inits` binds them, and no root
module may import the lexicon. Two contracts broke on the old shape, and behind
them sat the real problem — five of lexicon's ten modules were exempt from every
contract because their names matched no layer.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 1+4 — Cast runtime leaves the author's door; CLI to root | done | `13ac4c8` |
| 2 — The grimoire stops speaking the wire protocol | done | `e51f6d2` |
| 3 — Every lexicon module sits in a layer | done | `08f8f07` |
| 5 — Reconcile the record | done | this commit |

Gates after each step: 128 tests, **31 import-linter contracts**, pylint 10.00,
mypy clean, vulture clean.

## Where the plan was wrong

Recorded because each cost a round trip:

1. **Step 2 as written was void.** It moved `_links` to root on the grounds that
   only the CLI used it — but Step 1+4 put the CLI *inside* lexicon, so `_links`
   gained an in-package consumer. Replaced with the wire decoupling.
2. **Step 1 could not go green alone.** Deleting `entry.py` left `inits/cli.py`
   importing `vekna.lexicon._gates`, which ruff rejects. Steps 1 and 4 had to
   land together; the sequencing was the only real blocker.
3. **The CLI does not go to root `gates/`.** Root `gates` may import only root
   `pacts`, and may not import root `inits` — so a click command there could not
   reach the runtime. The click tree lives in `inits/cli.py`; root `gates` stays
   empty until 0.6.0 gives it daemon commands.
4. **The dynamic import needs no mypy override.** `importlib.import_module`
   returns `ModuleType`, so `cast()` against a `Protocol` typechecks under
   `disallow_any_expr`. The old `inits/cast.py` needed one because it used bare
   `getattr`.

## Friction

- **import-linter's layer delimiters are the opposite of the intuitive
  reading.** `:` means "same layer, may import each other"; `|` is the
  *independent* one. A contract written with `:` passed while a deliberately
  reintroduced violation sat in the tree. (Moot now — the `layers` contracts
  were replaced by per-layer `forbidden` ones — but the lesson stands: verify a
  new contract by breaking it on purpose.)
- **A `forbidden` contract does not catch descendant-to-descendant imports.**
  `mills` forbidding `vekna.mills` stayed KEPT while a sibling import sat there;
  only the `independence` contract caught it.
- **Private nested packages have no legal sibling import.** `from .._pacts`
  trips ruff's `TID252`, `from vekna.lexicon._pacts` trips `PLC2701`. Setting
  `src = ["src"]` does not help. Resolved with a `PLC2701` per-file-ignore
  scoped to `src/vekna/lexicon/**`.

## Remaining

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the whole 0.3.0 story.
   Bump only on explicit request.
2. **`parallel`** — owed from 0.2.0. Note the medium registry is a module-level
   singleton; that is what needs rethinking before casts can run concurrently.
3. **Manual smoke test with the real SDK.** Every `coding` test runs against a
   stub, and `coding_claude` dispatches on `runtime_checkable` protocols, which
   check attribute *presence* only. Still the one place the suite can be green
   while the integration is wrong; owed before any 0.3.0 tag.
4. **0.6.0 owes the `RiteEvent → WireMessage` projection.** `vekna.wire` is
   dormant until then — zero importers in `src/`, by design.
5. **Deferred, all deliberate:** `_parse_flags` accepts a trailing flag with no
   value; `Grimoire._events` grows unbounded and only tests read it;
   `test_probe.py` binds a real unix socket under `tests/unit/`;
   `_validate_output` catches `(ValidationError, ValueError)` where the first
   subclasses the second; `probe_daemon`'s discarded result and the empty
   `_gates.py` / `_edges.py` placeholders stay until 0.6.0.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` / `mise run il` for verification.
  Check the exit code — mise reports failures as `ERROR task failed` while
  pylint still prints `10.00/10` above it.
- `CLAUDE.md`'s layer list still describes `gates → links → mills → specs →
  pacts` as an ordering; the contracts now make `gates` pacts-only. Worth a
  look next time it is edited.
