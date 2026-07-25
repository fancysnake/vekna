# Current Task

**Task:** 0.3.0 review remediation + tmux removal
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete (commit `1d8fb4d`)
**Review:** PR [#50](https://github.com/fancysnake/vekna/pull/50), comment of
2026-07-25 (items 1–16)
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — all thirteen steps landed; awaiting review

## Context

Vekna is now `lexicon` + `folio` + `wire` + a thin `inits` CLI. The tmux
focus-switcher it began as is gone: Claude Code ships its own notifications
and nothing else consumed it. Everything the PR review raised at P1–P3 is
fixed on that smaller surface, so the reborn line starts with no known
defects.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 0 — Delete the tmux subsystem | done | `aefa343` |
| 1 — One rite context manager | done | `bd9eb6d` |
| 2 — `_gates` input handling | done | `7280d3a` |
| 3 — Typed `rituals` entry points | done | `215a20e` |
| 4 — Framing out of `wire/_pacts` | done | `9392f52` |
| 5 — A typed, closed focus reply | done | `8113f62` |
| 6 — Explicit registration, one delta sink | done | `99d5871` |
| 7 — `--prompt` through the registry | done | `846c359` |
| 8 — Vocabulary and conformance sweep | done | `268b63d` |
| 9 — Split `lexicon/_dispatch` | done | `7f2def4` |
| 10 — Two doors | done | `b4f1824` |
| 11 — Test layout and fixtures | done | `1c228a8` |
| 12 — Docs, changelog, task record | done | this commit |

## Where the review was wrong

Recorded because PLAN.md repeated these claims before they were tested:

1. **`_loader` is not strictly typable.** `exec_module`, `vars(module)` and
   `tomllib.load` all return `dict[str, Any]`, so it needs its own
   `disallow_any_expr = false`. The override count went 1 → 2, not 1 → 1.
   `_graph` *is* strict, which is the real win.
2. **`medium` does not belong in `_mills`.** `ParamSpec` forwarding is
   Any-tainted; moving it would have forced the engine to take an exemption.
3. **Dropping `extra="ignore"` fixes nothing** — `ignore` is pydantic's
   default. `FocusReply` needed `extra="forbid"`.
4. **The `sys.modules` purge in `test_coding_claude` had to stay.** It is
   needed because `_links` binds the SDK's names at import and each test
   installs its own stub — a separate concern from registration.
5. Smaller: `__all__` was 35 names, not 46; there were four ritual blobs, not
   five, and one differs genuinely (~27 lines saved, not ~80).

## Remaining

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the whole 0.3.0
   story including this remediation. Bump only on explicit request.
2. **`parallel`** — owed from 0.2.0, still deferred. The TUI spec assumes it.
3. **Manual smoke test with the real SDK.** Every `coding` test runs against a
   stubbed `claude_agent_sdk`; nothing has exercised the real one end-to-end.
   This is the largest untested surface left.
4. **P4 items 17–19 deliberately not done**: `probe_daemon`'s discarded result
   and `Channel.emit` stay until 0.6.0 decides their role. Both carry a
   comment saying so.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` for all verification (mise-managed env).
  Check the exit code — mise reports failures as `ERROR task failed` while
  pylint still prints `10.00/10` above it.
