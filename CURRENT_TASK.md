# Current Task

**Task:** Feature 0.3.0 — `folio/coding` + `folio/coding_claude`
**Spec:** `docs/reborn/03-coding-folios.md`
**Plan:** [`PLAN.md`](PLAN.md) — approved, in flight (commit `66d238e`)
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — all six steps landed; awaiting review

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
| 5 — `vekna rituals list` / `show` | done | `21ffa49` |
| 6 — Example, docs, changelog | done | `35b632e`, `088c1b3`, this commit |

Landed alongside the numbered steps: `ask_human` mid-rite (`169a8eb`),
shell output streamed into the rite (`1250951`), `current_rite_id` plus the
coverage that flushed out a broken `asyncio.gather` call (`8b27b2a`).

## Remaining

Nothing in the plan. Open questions for the next session:

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the full 0.3.0 story;
   the version bump was deliberately left for an explicit request.
2. **`parallel`** — owed from 0.2.0, deferred as a separate task. The TUI spec
   assumes it exists.
3. **Manual smoke test with the real SDK.** Every `coding` test runs against a
   stubbed `claude_agent_sdk` in `sys.modules`; nothing has exercised the real
   one end-to-end.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` for all verification (mise-managed env).
- Release bump only on explicit request.
