# High Magic — the factory

Not a bucket of ideas. An alternative timeline, the way Reborn was: what Reborn
did for one cast, this does for many. Vekna works at one cast per project.
The next level is not a fully autonomous system; it is the same vekna,
replicated and scaled. A project runs several casts at once across a pool of
worktrees, a ritual fans its work out into a queue instead of walking a list,
and one window shows the whole of it.

The shared context is still [`../reborn/common.md`](../reborn/common.md), whose
first line names `reborn/`, `eye/` and `hand/` as the tracks that assume it —
this one does too. It stays a delta rather than an edit in place because the
track is an experiment: rewriting common.md now would assert a decision that
[#101](https://github.com/fancysnake/vekna/issues/101),
[#104](https://github.com/fancysnake/vekna/issues/104) and
[#108](https://github.com/fancysnake/vekna/issues/108) still contradict. What
that document says that stops being true is listed below, and nowhere else.
[`plan.md`](plan.md) is the order this timeline goes in.

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
  one-cast-at-a-time refusal all go. What survives of
  [#101](https://github.com/fancysnake/vekna/issues/101) is the per-project
  scheduler, and it lives inside the daemon the way the hub does. **The word
  goes with the process.** What is left is a place rather than a person: a
  project's **circle** is its queue, its slots and its trees.

  Struck in common.md, in full: the **lich** role in the premise and the
  **Lich** and **Phylactery** glossary rows; the `lich "hollow-vesper"`
  diagram and its `phylactery: one registry row` line; the `LichRose` /
  `LichFell` / `LichStatus` and `CastRequested` / `CastRefused` /
  `CastKillRequested` wire rows, the first gone outright and the second
  re-aimed surface ↔ daemon with no routing by lich name; resolved decisions
  12 and 13, the refusal and the phylactery keyed by name; and the whole
  not-planned entry "two casts in one lich, or one lich over several project
  roots", both halves of which this track does on purpose.
- **The daemon starts casts.** common.md's premise gives spawning to the lich
  and leaves the daemon routing commands to it; here the daemon spawns `vekna
  cast` subprocesses itself, the way `--resume` already does, with a cwd. It
  still imports no lexicon and loads no ritual. **Worktrees are pooled,
  processes are not**: "pooled cast processes" stays not planned.
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

Outside common.md, one sentence dates with it: `CHANGELOG.md`'s 0.6.0 entry says
of the daemon "it observes and records; it starts nothing". True when it was
written, past tense here.

## The circle, as it is now

A per-project scheduler inside the daemon. Its numbers live in the project's
`.vekna.toml`, with a global default in the user config:

```toml
[circle]
processes = 4
worktrees = 2
prepare = "mise install && poetry install"
```

A cast is enqueued with what it needs: a slot always, a tree if its ritual
says so. The scheduler spawns it when both are free, in the tree it leased,
and releases both when the cast ends however it ends — or the slot alone,
earlier, when the cast blocks on a child it is waiting for.

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
- **Release**: after the cast ends, the daemon checks the tree and only then
  parks it. The check is its own step, because `git checkout` is not one — it
  carries local changes across a branch switch whenever they do not conflict,
  so a tree that failed nothing would still hand the next cast the last one's
  edits. A non-empty `git status --porcelain`, or a merge, rebase or
  cherry-pick in progress, marks the tree **blocked** and reports it; a clean
  tree gets `git checkout vekna/wt-<n>`. Gitignored files are not dirt: the
  venv and whatever else `prepare` left are the reason a tree is reused, and
  `--porcelain` does not list them. Nothing ever resets a tree; uncommitted
  work is somebody's until they say otherwise.
- **Crash**: a tree on a non-parking branch with no live cast is one a dead
  cast left behind. The daemon runs the same check and release on restart, so
  blocked-or-free is read off the tree, not remembered.
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
from vekna.folio.flow import await_cast, enqueue

cast_id = await enqueue("refresh", Sweep(pull_request=pr.number))   # proceed
report = await await_cast("refresh", Sweep(pull_request=pr.number))  # await
```

- `enqueue` returns a cast id and the step continues. `await_cast` waits for
  the child's result, validated against `output=` the way coding's is. Not
  `cast`: the noun is the project's central one, the verb is its CLI's, and
  `typing.cast` is imported in `inits/cli.py` already — a ritual importing
  `cast` makes every later sentence about a cast ambiguous.
- **An awaiting parent gives up its process slot** and keeps its tree. A
  parent blocked in `await_cast` is idle; holding a slot while its child
  queues for one is the deadlock the mid-cast tree lease is refused for
  above, and with `processes = 4` it takes four parents. The tree stays
  leased, because the parent's checkout has to survive until it resumes.
- **The result rides on the wire.** `CastGoodbye` today is status and detail,
  and detail is prose for a human. It gains a result field carrying the
  child's return model as JSON, the way `CastHello` already carries
  components; the parent validates it against `output=`, being the side with
  the lexicon. The daemon relays it and validates nothing.
- **A queued cast is a run record** with status `queued` and no events. `vekna
  log` lists it, prune spares it as it spares a running one, the dashboard
  gains the status.
- **The payload rides in that record, and spawn is by id.** The typed
  components are dumped into the record's `CastHello` — by the enqueuing cast,
  which is the process that has the lexicon and the model — and the daemon
  spawns `vekna cast --resume <cast_id>` with a cwd. The child reads its own
  record and validates the components against the ritual's model, exactly as
  `--resume` does today (`_resume`, `lexicon/_inits.py`). Nothing typed crosses
  the daemon, which is what lets it stay a process that loads no lexicon.
- **The ritual name rides there too**, resolved by the enqueuing cast rather
  than by the daemon, which has no compendium to resolve it against. It has to
  be a name that means one ritual from any directory, and that is what makes
  [#128](https://github.com/fancysnake/vekna/issues/128) a dependency.
- **Standalone denies**, like locks. A cast with no daemon has no queue, and
  a queue that silently ran inline would hide the one thing this exists for.
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

Groups 1 and 2 of [`plan.md`](plan.md), which say which issues and in what
order. Nothing here restates them.

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
