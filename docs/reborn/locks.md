# Locks, coordinated

See [common.md](common.md) — wire lock messages, replay rebuilds lock state,
standalone modes.

## Goal

A real concurrency primitive, not a coding-mode footnote. The lock API with
hierarchical keys and the `Scope` helper, and the daemon-side manager that makes
them mean something. Coordinated from the first line: no permissive stage to
ship and then flip out of, and no state where `lock()` succeeds while promising
nothing.

## What ships

- Lock API: `lock(...)` async context manager + `Scope` helper.
- Hierarchical colon-keyed resources, intention-lock semantics.
- **Lock manager** — project- and system-level intention-lock tree in the
  daemon, with real coordination. Lock state rebuilt per cast from replayed
  grimoire events, so a daemon that starts mid-cast learns every lock that cast
  thinks it holds.
- `vekna locks` (current locks + holders), `vekna unlock <key>` (admin
  override, confirmation).
- Standalone modes `allow` / `warn` / `deny` — what a cast does with no daemon
  listening. **Default `deny`.**
- One-time-per-cast banner on first lock acquisition in `warn`.

## Keys + semantics

Free-form colon-hierarchical strings: `project`, `project:edit`,
`project:edit:tests`, `system:claude-quota`, `db:vekna-prod`.

Intention-lock style. The lock manager is a tree; acquisition walks ancestors
(any held → deny) and descendants (any held → deny). Siblings independent:

- Holding `project:edit` blocks `project`, `project:edit:tests`,
  `project:edit:*`.
- Holding `project:edit:tests` blocks `project`, `project:edit`,
  `project:edit:tests:*`. Does **not** block `project:edit:docs`.

The **cast** holds the lock. A release token authorises release; the
`async with lock(...)` block scopes the release call.

```python
from vekna.lexicon import Scope, lock

s = Scope("project") / "edit" / "tests"
async with lock(s):
    await coding(prompt="...")
```

`/` builds the path; the wire ships strings. `lock("project:edit:tests")`
works too — helper is sugar.

## Standalone modes

A cast with no daemon has no coordinator, and the setting says what to do about
it:

| Mode    | Behaviour                                | Use         |
|---------|------------------------------------------|-------------|
| `allow` | Locks succeed silently                   | CI, scripts |
| `warn`  | Locks succeed with red banner + log line | Interactive |
| `deny`  | Locks block with retry/quit prompt       | Default     |

```toml
[locks]
standalone = "deny"
```

Banner appears once per cast on first acquisition (not per lock):

```text
⚠ STANDALONE MODE — LOCKS NOT COORDINATED
   This cast holds locks locally only. Concurrent casts on this
   project may corrupt each other. Start vekna for real safety.
```

`deny` blocking prompt (same shape as other "needs vekna" features):

```text
✋ rite "fix" requested lock "project:edit"
   no daemon detected — locks require a running vekna.
   [r] retry · [q] quit cast
```

Retry triggers the connection probe; if the daemon started meanwhile, the lock
acquires and the cast continues.

## Scope

- Lexicon: `lock`, `Scope` public surface; lock ops emit grimoire events
  (`LockAcquireRequested`/`LockGranted`/`LockDenied`/`LockReleased`).
- `vekna.wire` lock message kinds.
- `mills/` — the lock tree, and rebuilding it from a replayed cast.
- `gates/cli/click/` — `locks`, `unlock`.
- Standalone-mode resolution from config + `VEKNA_STANDALONE_LOCKS` env.

## Out of scope

Lock queues — an acquisition is granted or denied, never parked behind another.
Cross-machine coordination.

## Acceptance

- Hierarchical keys deny ancestors/descendants, allow siblings (unit tests on
  the tree).
- Two casts attached to one daemon: the second is denied a key the first holds,
  and granted it once the first releases.
- A daemon restarted mid-cast rebuilds that cast's locks from the replay, and
  denies a sibling cast accordingly.
- `warn` shows the banner once per cast; locks still succeed. `allow` is
  silent. `deny` without vekna blocks with the retry/quit prompt.
- `mise run fullcheck` passes.
