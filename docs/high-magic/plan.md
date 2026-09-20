# High Magic — the order

The one page under `docs/` that says *when*. [`README.md`](README.md) says
what; this says what goes first and why, grouped by what unblocks what. An
issue is named by number; a group is done when its issues are closed.

Revise it when the order changes, not when something ships. Shipping is
`CHANGELOG.md`'s to record.

## 1. In flight

- [#78](https://github.com/fancysnake/vekna/issues/78) — prune reports what
  it could not remove. `PLAN.md` is written for it.

## 2. Break the API once

The queue spawns by name and the `enqueue` medium should land on the surface
the engine will keep, not the one it is about to lose.

- [#103](https://github.com/fancysnake/vekna/issues/103) — steps as DTOs. The
  one breaking change; everything after it builds on the new shape.
- [#128](https://github.com/fancysnake/vekna/issues/128) — namespaces for tome
  rituals. Spawn by name needs unambiguous names.
- [#129](https://github.com/fancysnake/vekna/issues/129) — every collision at
  once. Same code as #128; done together.

## 3. Hand prerequisites

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

## 4. Journal hygiene

The queue stores its entries as run records, so these stop being cosmetic.

- [#77](https://github.com/fancysnake/vekna/issues/77) — the event log stays
  a prefix.
- [#134](https://github.com/fancysnake/vekna/issues/134) — unreadable run
  directories do not leak.

## 5. The factory

New issues, replacing [#101](https://github.com/fancysnake/vekna/issues/101).
Each is filed when the one before it is closed, so its scope is written
against what actually shipped.

1. **The daemon that outlives the window.** Detach on first start, `vekna`
   attaches, `q` detaches, `vekna stop`. Project identity from the git
   common dir on `CastHello`. The project view as the default screen, the
   global one as a tab.
2. **Spawn.** The daemon runs `vekna cast <name>` with a cwd, behind a
   process-slot counter from `[lich] processes`. Answers over the wire for
   spawned casts. Start a ritual from the dashboard.
3. **The worktree pool.** Parking branches, derivation from `git worktree
   list`, lease and release, `prepare`, `[lich] worktrees`,
   `@ritual(worktree=True)`.
4. **The queue.** `enqueue` and `cast` in `folio/flow`, the `queued` run
   record, prune sparing it, the dashboard status, the spawning cast on
   `CastHello`.
5. [#94](https://github.com/fancysnake/vekna/issues/94) — a component
   answered once per repo. Enqueued casts carry components nobody typed.

## 6. Locks

- [#102](https://github.com/fancysnake/vekna/issues/102) — coordinated locks.
  The scheduler's counters do not need the tree; `system:claude-quota`
  across many parallel casts is the first thing that will. Swap ahead of
  group 5 if `lock()` is wanted sooner — the scheduler never reads it either
  way.

## 7. Cabinet

After group 5 ships, in [cabinet](https://github.com/fancysnake/cabinet):
one pull request per cast, `list_prs` enqueues and is done, `sync_base`
without a checkout, `check_clean` and `release` removed.

## 8. Surfaces

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

Nothing above depends on these. Pick one up when it is the cheapest thing on
the table.

[#91](https://github.com/fancysnake/vekna/issues/91),
[#92](https://github.com/fancysnake/vekna/issues/92),
[#93](https://github.com/fancysnake/vekna/issues/93),
[#95](https://github.com/fancysnake/vekna/issues/95),
[#96](https://github.com/fancysnake/vekna/issues/96),
[#97](https://github.com/fancysnake/vekna/issues/97),
[#98](https://github.com/fancysnake/vekna/issues/98),
[#100](https://github.com/fancysnake/vekna/issues/100),
[#112](https://github.com/fancysnake/vekna/issues/112),
[#114](https://github.com/fancysnake/vekna/issues/114),
[#115](https://github.com/fancysnake/vekna/issues/115),
[#131](https://github.com/fancysnake/vekna/issues/131),
[#132](https://github.com/fancysnake/vekna/issues/132),
[#79](https://github.com/fancysnake/vekna/issues/79).

[#133](https://github.com/fancysnake/vekna/issues/133) is the 1.0 bump
itself.
