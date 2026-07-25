# Current Task

**Task:** Feature 0.3.0 — `folio/coding` + `folio/coding_claude`
**Spec:** `docs/reborn/03-coding-folios.md`
**Plan:** [`PLAN.md`](PLAN.md) — approved, in flight (commit `66d238e`)
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT — Steps 0–4 landed; Step 5 next

## Context

0.2.0 shipped and released (2026-06-28). Product direction: daily dev
workflows (PR triage, merge babysitting) as rituals — 0.3.0's `coding` medium
is the last missing primitive for those. The four open decisions this file
used to track were all resolved in PLAN.md's "Approved design decisions".

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 0 — Decide consolidation | done | `589d12a` |
| 1 — Live grimoire + deltas | done | `c3e3b79` |
| 2 — `folio/coding` + focus registry | done | `ee7d280` |
| 3 — `folio/coding_claude` + packaging | done | `68a86a3` |
| 4 — `vekna cast --prompt` sugar | done | `470799a` |
| 5 — `vekna rituals list` / `show` | **not started** | — |
| 6 — Example, docs, changelog | partial | `35b632e`, `088c1b3` |

Landed alongside the numbered steps: `ask_human` mid-rite (`169a8eb`),
shell output streamed into the rite (`1250951`), `current_rite_id` plus the
coverage that flushed out a broken `asyncio.gather` call (`8b27b2a`).

## Remaining

1. **Step 5 — `vekna rituals list` / `show`.** Nothing exists yet: no
   `dispatch_rituals` in `inits/cast.py`, no `rituals` click group, no
   `rituals_main`. The step graph is the only under-specified piece of the
   plan — "best-effort" AST scan for `goto(<step>` targets, shape TBD on
   contact.
2. **Step 6 — docs + changelog.** `rituals.py` at the root and `cover_diff`
   are done; `docs/reborn/03-coding-folios.md` and `00-common.md` still
   describe the pre-delivery design (`--auto-approve`, `coding-claude`
   extra), and `CHANGELOG.md` `[Unreleased]` is empty.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` for all verification (mise-managed env).
- Release bump only on explicit request.
