# High Magic — the order

The order this timeline goes in, and nobody else's: the issues outside it are
grouped by category, not by release. [`README.md`](README.md) says what this
track is; this says what goes first and why, grouped by what unblocks what. An
issue is named by number.

Revise it when the order changes, not when something ships. Shipping is
`CHANGELOG.md`'s to record, and what is closed is GitHub's to show.

## 1. Break the API once

The queue carries a ritual name and the `enqueue` medium should land on the
surface the engine will keep, not the one it is about to lose.

- [#103](https://github.com/fancysnake/vekna/issues/103) — steps as DTOs. The
  one breaking change, if it lands at all; everything after it builds on the
  new shape.
- [#128](https://github.com/fancysnake/vekna/issues/128) — namespaces for tome
  rituals. A queued name resolved from any directory needs to be unambiguous.
- [#129](https://github.com/fancysnake/vekna/issues/129) — every collision at
  once. Same code as #128; done together.

## 2. Hand prerequisites

In dependency order: a timeout and a budget overrun both arrive as a
`Failure`, so the failure route comes first.

- [#113](https://github.com/fancysnake/vekna/issues/113) — failure as a
  transition, including the unattended half. A spawned cast has no terminal;
  a `decide` it cannot ask must fail at the boundary with a route.
- [#110](https://github.com/fancysnake/vekna/issues/110) — cancellation,
  `timeout`, `race`. Kill on a queued or running cast has to reach the agent
  subprocess.
- [#111](https://github.com/fancysnake/vekna/issues/111) — cast budgets. One
  cast overspending is a nuisance; thirty enqueued ones doing it is a bill.

## 3. Journal hygiene

The queue stores its entries as run records, so these stop being cosmetic.

- [#78](https://github.com/fancysnake/vekna/issues/78) — prune reports what it
  could not remove.
- [#77](https://github.com/fancysnake/vekna/issues/77) — the event log stays
  a prefix.
- [#134](https://github.com/fancysnake/vekna/issues/134) — unreadable run
  directories do not leak.

## 4. The factory

New issues, replacing [#101](https://github.com/fancysnake/vekna/issues/101),
filed in this order — each written against the shape the one before it leaves.

1. **The daemon that outlives the window.** Detach on first start, `vekna`
   attaches, `q` detaches, `vekna stop`. Project identity from the git
   common dir on `CastHello`. The project view as the default screen, the
   global one as a tab.
2. **Spawn.** The daemon runs `vekna cast --resume <cast_id>` with a cwd,
   behind a process-slot counter from `[circle] processes`. Answers over the
   wire for spawned casts. Start a ritual from the dashboard.
3. **The worktree pool.** Parking branches, derivation from `git worktree
   list`, lease and release, `prepare`, `[circle] worktrees`,
   `@ritual(worktree=True)`.
4. **The queue.** `enqueue` and `cast` in `folio/flow`, the `queued` run
   record, prune sparing it, the dashboard status, the spawning cast on
   `CastHello`.
5. [#94](https://github.com/fancysnake/vekna/issues/94) — a component
   answered once per repo. Enqueued casts carry components nobody typed.

## 5. Locks

- [#102](https://github.com/fancysnake/vekna/issues/102) — coordinated locks.
  The scheduler's counters do not need the tree; `system:claude-quota`
  across many parallel casts is the first thing that will. Swap ahead of
  group 4 if `lock()` is wanted sooner — the scheduler never reads it either
  way.

## 6. Cabinet

After group 4 ships, in [cabinet](https://github.com/fancysnake/cabinet):
one pull request per cast, `list_prs` enqueues and is done, `sync_base`
without a checkout, `check_clean` and `release` removed.

## 7. Surfaces

Cheapest first.

- [#105](https://github.com/fancysnake/vekna/issues/105) — the ritual's own
  status line. Pays off the moment several casts run.
- [#99](https://github.com/fancysnake/vekna/issues/99) — Pushover, per
  project.
- [#104](https://github.com/fancysnake/vekna/issues/104) — Discord, on the
  channel-per-project, thread-per-cast shape.
- [#109](https://github.com/fancysnake/vekna/issues/109) — the graph drawn,
  once #113's edges exist to draw.
- [#107](https://github.com/fancysnake/vekna/issues/107) — TUI, and
  [#108](https://github.com/fancysnake/vekna/issues/108) — web, after the
  project view has settled.

## Unordered

Everything not named above. Nothing above depends on it; pick one up when it
is the cheapest thing on the table. The
[milestones](https://github.com/fancysnake/vekna/milestones) are the list, and
they stay current on their own.

[#133](https://github.com/fancysnake/vekna/issues/133) is the 1.0 bump
itself.
