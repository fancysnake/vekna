# Feature — Locks API (`warn` default)

**Version:** `0.5.0`

See [00-common.md](00-common.md) — wire lock messages, replay rebuilds lock
state, standalone modes.

## Goal

Real concurrency primitive, not a coding-mode footnote. Ship the lock API with
hierarchical keys and the `Scope` helper. At 0.5.0 there is **no real
coordination yet** — locks are honest about it via the standalone banner. The
daemon provides actual coordination at 0.6.0.

## What ships

- Lock API: `lock(...)` async context manager + `Scope` helper.
- Hierarchical colon-keyed resources, intention-lock semantics.
- Standalone modes `allow` / `warn` / `deny`; **default `warn`** at 0.5.0.
- One-time-per-cast banner on first lock acquisition.

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

| Mode    | Behaviour                                | Use         |
|---------|------------------------------------------|-------------|
| `allow` | Locks succeed silently                   | CI, scripts |
| `warn`  | Locks succeed with red banner + log line | Interactive |
| `deny`  | Locks block with retry/quit prompt       | With vekna  |

**Default `warn` at 0.5.0; flips to `deny` when the daemon lands (0.6.0).**
Banner appears once per cast on first acquisition (not per lock):

```
⚠ STANDALONE MODE — LOCKS NOT COORDINATED
   This cast holds locks locally only. Concurrent casts on this
   project may corrupt each other. Start vekna for real safety.
```

`deny` blocking prompt (same shape as other "needs vekna" features):

```
✋ rite "fix" requested lock "project:edit"
   no daemon detected — locks require a running vekna.
   [r] retry · [q] quit cast
```

Retry triggers the connection probe; if the daemon started meanwhile, the lock
acquires and the cast continues.

## Scope

- Lexicon: `lock`, `Scope` public surface; lock ops emit grimoire events
  (`LockAcquireRequested`/`LockGranted`/`LockDenied`/`LockReleased`).
- `vekna.wire` lock message kinds (defined at v0.2.0, exercised here).
- Standalone-mode resolution from config + `VEKNA_STANDALONE_LOCKS` env.

## Out of scope

Real cross-cast coordination (0.6.0 daemon lock manager). `deny` requiring a
live daemon is correct — it blocks without one.

## Acceptance

- Hierarchical keys deny ancestors/descendants, allow siblings (unit tests on
  the tree).
- `warn` shows the banner once per cast; locks still succeed.
- `allow` is silent.
- `deny` without vekna blocks with the retry/quit prompt.
- `mise run fullcheck` passes.
