# High Magic — the factory

Not a bucket of ideas. An alternative timeline, the way Reborn was: what Reborn
did for one cast, this does for many. Vekna works at one cast per project.
The next level is not a fully autonomous system; it is the same vekna,
replicated and scaled. A project runs several casts at once across a pool of
worktrees, a ritual fans its work out into a queue instead of walking a list,
and one window shows the whole of it.

The shared context is still [`../reborn/common.md`](../reborn/common.md). This
page is the delta: what that document says that stops being true, and what is
added. [`plan.md`](plan.md) is the order.

## Two ideas

1. **Worktrees, managed.** Today the operator makes the worktrees and juggles
   them, which is the same time sink vekna was written to remove one level
   down. Run vekna on a project, say how many casts may run at once and how
   many worktrees they may use, and start or enqueue rituals. The two numbers
   differ because some rites need no checkout: reading a CI board, listing
   pull requests, deciding.
2. **Queued casts.** A sweep ritual today takes pull requests one by one, in
   its own payload
   ([cabinet](https://github.com/fancysnake/cabinet)'s `Run.queue`). Instead
   its first step creates one cast per pull request and finishes. A ritual
   decides where it enqueues and proceeds, and where it awaits. A cast that
   checks CI needs no worktree; the fix casts it enqueues wait in the queue
   until a tree and a slot are free.

Parallelism lives **between casts**, not between steps. Steps stay sequential
and the boundary stays the unit of determinism, which is what
[#103](https://github.com/fancysnake/vekna/issues/103) already says under
"not the question". Blast radius stays one cast process.

## What changes in common.md

- **The lich merges into the daemon and the dashboard.** Bare `vekna` in a
  project opens that project's dashboard: its casts, its queue, its slots and
  trees; trigger a ritual, attach to a cast to answer it. The lich as a
  separate process, its generated name, its phylactery row, and its
  one-cast-at-a-time refusal all go. Resolved decision 12 falls, and "two
  casts in one lich" leaves the not-planned list. What survives of
  [#101](https://github.com/fancysnake/vekna/issues/101) is the per-project
  scheduler, and it lives inside the daemon the way the hub does. The word
  survives too: a project's **lich** is its queue, its slots and its trees.
- **The daemon starts casts.** The 0.6.0 line "it observes and records; it
  starts nothing" moves to the past tense. It spawns `vekna cast` subprocesses
  the way `--continue` already does, with a cwd; it still imports no lexicon
  and loads no ritual. **Worktrees are pooled, processes are not**: "pooled
  cast processes" stays not planned.
- **The daemon outlives the window.** Queued casts cannot die because a
  terminal closed. It detaches on first start, every `vekna` attaches as a
  peer, `q` detaches, and `vekna stop` is the explicit end. Today the first
  `vekna` is the daemon and `q` closes the socket with it.
- **A project is its git common dir, not the cwd.** A cast in a pooled tree
  groups under the repository it belongs to. `CastHello` gains `project`,
  resolved once at spawn; `project_root` stays the directory the cast runs
  in. The view filter and the scheduler key on the former.
- **Answers travel over the wire for spawned casts.** They have no terminal,
  so the blocking-stdin problem that deferred answering from the dashboard in
  0.6.0 does not apply to them. `DecideResolved` in the daemon-to-cast
  direction, designed for a takeover, is what "attach to answer" uses. A cast
  run by hand keeps its stdin exactly as now.
- **Locks stay binary.** [#102](https://github.com/fancysnake/vekna/issues/102)
  keeps its "never parked" rule and its hierarchical tree for in-cast keys.
  Waiting for a slot or a tree is the queue's job, not the lock tree's: the
  scheduler holds two counters, and a queued cast parks in the queue.
- **A global view is a tab, read only.** One daemon per user holds every
  project's casts on one socket, so tabs across projects need no extra
  networking. That only becomes true across machines, which stays out of
  scope.

## The lich, as it is now

A per-project scheduler inside the daemon. Its numbers live in the project's
`.vekna.toml`, with a global default in the user config:

```toml
[lich]
processes = 4
worktrees = 2
prepare = "mise install && poetry install"
```

A cast is enqueued with what it needs: a slot always, a tree if its ritual
says so. The scheduler spawns it when both are free, in the tree it leased,
and releases both when the cast ends however it ends.

### Worktrees

- **Each tree has a parking branch**, `vekna/wt-<n>`, and stands on it whenever
  no cast holds it. A branch can be checked out in one tree at a time, so a
  tree idle on a real branch would lock that branch for every other tree.
- **The pool is derived from git, not recorded.** `git worktree list
  --porcelain` filtered on the parking prefix *is* the pool. After a daemon
  restart the state is rebuilt from git plus the journal, the way the hub's
  views are derived rather than stored.
- **Lease**: a tree is free when its HEAD is its parking branch and no live
  cast holds it. The cast checks out whatever it needs, as cabinet's rituals
  do today.
- **Release**: after the cast ends, the daemon runs `git checkout
  vekna/wt-<n>` in the tree. That one command is also the cleanliness check:
  it fails on a dirty tree or a merge in progress. A failed release marks the
  tree **blocked** and reports it. Nothing ever resets a tree; uncommitted
  work is somebody's until they say otherwise.
- **Crash**: a tree on a non-parking branch with no live cast is one a dead
  cast left behind. The daemon attempts the same release on restart, and
  blocked-or-free is git's answer, not a remembered one.
- **Creation** is on demand up to the configured count: `git worktree add
  <path> -b vekna/wt-<n> <base>`, then `prepare` once. Trees are persistent:
  a fresh tree has no venv, no `mise trust`, no gitignored files, and
  installing that per cast is minutes, so a tree is prepared once and reused.
  Never removed automatically. They live under the state directory,
  `~/.local/state/vekna/worktrees/<project>/<n>`, where editors and `mise`
  do not stumble on them.
- **Parking branches never leave the machine.** Not pushed, not offered.
- **The need is declared at the ritual**, `@ritual(worktree=True)`, and the
  tree is leased before spawn. A mid-cast lease would hold a slot while
  waiting for a tree, and with every slot waiting that is a deadlock with no
  ritual code at fault.
- **The base is synced without a checkout** in a pool tree: the primary tree
  holds `main`. `git fetch` plus `merge --ff-only` against the remote ref.
  Cabinet's `sync_base` is the one line this changes.

### The queue

Two mediums, in `folio/flow`, over the daemon link a cast already has:

```python
from vekna.folio.flow import cast, enqueue

cast_id = await enqueue("refresh", Sweep(pull_request=pr.number))   # proceed
report = await cast("refresh", Sweep(pull_request=pr.number))       # await
```

- `enqueue` returns a cast id and the step continues. `cast` waits for the
  child's result, validated against `output=` the way coding's is.
- Spawn is **by ritual name**, since the daemon runs `vekna cast <name>` and
  loads nothing. That is what makes
  [#128](https://github.com/fancysnake/vekna/issues/128) a dependency.
- **Standalone denies**, like locks. A cast with no daemon has no queue, and
  a queue that silently ran inline would hide the one thing this exists for.
- **A queued cast is a run record** with status `queued` and no events. `vekna
  log` lists it, prune spares it as it spares a running one, the dashboard
  gains the status.
- The child is an ordinary cast with its own journal, hello and goodbye. One
  field on `CastHello` says which cast enqueued it, and "what did this sweep
  spawn" is a query over the journal, not a list something maintains.

## Surfaces

- **The project dashboard** is bare `vekna`. Casts, queue, slots, trees;
  start a ritual, attach to a cast. The TUI
  ([#107](https://github.com/fancysnake/vekna/issues/107)) and the web view
  ([#108](https://github.com/fancysnake/vekna/issues/108)) render the same
  thing; "the lich's page" in #108 is the project's page.
- **Pushover** ([#99](https://github.com/fancysnake/vekna/issues/99)) is per
  project by config, and one channel for all of a project's casts is right:
  the message names the ritual and the cast.
- **Discord** ([#104](https://github.com/fancysnake/vekna/issues/104)): a
  channel per project, a **thread per cast**. A channel per cast would fill a
  server in a week; threads auto-archive and archived ones are unlimited. A
  decide posts into the cast's thread and a reply there answers it. The
  per-lich channel in the issue is the per-project channel unchanged.

## What it depends on

Hand issues that are not started, in the order they bite:

1. [#113](https://github.com/fancysnake/vekna/issues/113), the unattended
   half. A spawned cast that reaches a `decide` with no surface attached must
   fail at that boundary with a route, not die on the third empty line.
2. [#111](https://github.com/fancysnake/vekna/issues/111), budgets. One cast
   overspending is a nuisance; thirty enqueued ones doing it is a bill.
3. [#110](https://github.com/fancysnake/vekna/issues/110), cancellation. Kill
   on a queued or running job has to reach the agent subprocess.
4. [#128](https://github.com/fancysnake/vekna/issues/128), namespaces. Spawn
   is by name.
5. [#103](https://github.com/fancysnake/vekna/issues/103) first, if at all.
   It breaks the public surface; landing it before `enqueue` exists is one
   break instead of two.

## What it does to cabinet

- `list_prs` enqueues one cast per pull request and is done. `Run.queue` and
  `next_pr` go; a cast is one pull request.
- `check_clean` and `release` move out of the ritual: the daemon owns both
  ends of a tree.
- `sync_base` loses its checkout.
- Anything the gate needs at runtime that is not committed (`.env`, a venv)
  is `prepare`'s job.

## Still not planned

Pooled cast processes. Cross-machine anything. A tree reset by the daemon.
Concurrent steps in one cast.

## Open

- The track's name. The rule says Vecna lore, and High Magic is not; Cult
  fits the shape. Whether the named-release idea survives at all is a
  separate question this page does not settle.
- A spawned cast at a `decide` with nobody attached: fail at once, or wait
  with a timeout from the budget, then fail. Waiting holds a slot and a tree.
- The parking prefix, fixed or a config key. Fixed, unless something needs
  it otherwise: a configurable prefix is a second thing the derivation reads.
- Whether these become issues, and which existing ones they replace.
