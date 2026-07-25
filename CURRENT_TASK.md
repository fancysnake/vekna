# Current Task

**Task:** post-reborn review remediation
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete (commit `fe99c99`)
**Review:** PR [#50](https://github.com/fancysnake/vekna/pull/50), GLIMPSE-lens
comment of 2026-07-25
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — all five steps landed; awaiting review

## Context

Vekna is `lexicon` + `folio` + `wire` + a thin `inits` CLI. This cycle fixed the
two P1 crashes a normal user could hit and closed the P2 the review actually
turned up: the layer table in `docs/architecture.md` was a convention nothing
checked, and two modules had already inverted against it.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 1 — Ritual sources dedupe, silently | done | `0a053c8` |
| 2 — Long output lines stop crashing the cast | done | `09f6b64` |
| 3 — The layer table becomes true | done | `eee02b0` |
| 4 — The contract that keeps it true | done | `b84af2c` |
| 5 — Reconcile the record | done | this commit |

Gates after each step: 128 tests, 11 import-linter contracts, pylint 10.00,
vulture clean.

## What the fixes actually were

1. **Ritual sources are deduped by resolved path**, not by declining to search
   when config names files — the skip rule would have let a global
   `config.toml` suppress every project's own `rituals.py`.
2. **`run_bash` iterates chunks, not lines.** The 1 MiB cap was guarding
   nothing (`ShellResult.stdout` retains everything regardless) and its only
   effect was to crash. `_Chunks` exists because the house rule bans `while`
   and `StreamReader.__aiter__` yields the lines being avoided.
3. **`folio/shell` and `wire` lost their `_mills`**; each folio gained an
   `_inits.py` for its `register()`.

## Friction

- **import-linter's layer delimiters are the opposite of the intuitive
  reading.** `:` means "same layer, may import each other"; `|` is the
  *independent* one that forbids it. The first draft of the `layers` contracts
  used `:` and passed while a deliberately reintroduced violation sat in the
  tree — a vacuous green. Any new layers contract must be checked by breaking
  it on purpose once, which is now a step in its own right.

## Remaining

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the whole 0.3.0 story
   including both remediation cycles. Bump only on explicit request.
2. **`parallel`** — owed from 0.2.0, still deferred. The TUI spec assumes it.
   Note the medium registry is a module-level singleton, which is the thing
   that will need rethinking when casts can run concurrently.
3. **Manual smoke test with the real SDK.** Every `coding` test runs against a
   stubbed `claude_agent_sdk`, and `coding_claude` dispatches on
   `runtime_checkable` protocols, which check attribute *presence* only. Still
   the one place the suite can be green while the integration is wrong; owed
   before any 0.3.0 tag.
4. **Deferred from this review, all deliberate:**
   - `_parse_flags` accepts a trailing flag with no value (`--name` →
     `{'name': ''}`) while `--name --other x` correctly errors.
   - `Grimoire._events` grows without bound and nothing in `src/` reads it;
     wants the 0.6.0 daemon decision about journal-vs-buffer.
   - `test_probe.py` binds a real unix socket under `tests/unit/`.
   - `_validate_output` catches `(ValidationError, ValueError)`; the former
     subclasses the latter.
   - `probe_daemon`'s discarded result and `Channel.emit` stay until 0.6.0
     decides their role. Both carry a comment saying so.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- `mise run test` / `mise run check` for all verification (mise-managed env).
  Check the exit code — mise reports failures as `ERROR task failed` while
  pylint still prints `10.00/10` above it.
