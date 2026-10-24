# Vekna's own rituals

This project casts them on itself.

```bash
vekna cast cover_diff [--bound N]
vekna cast review [--base <ref>] [--only <file>] [--focus <text>]
vekna cast merge_ready [--bound N]
vekna cast triage --link <url>
vekna cast nap [--naps N] [--seconds N]
vekna cast tree [--dirty true]
vekna cast sweep [--base-branch <ref>] [--max-prs N]
vekna cast ci_watch --pull-request N [--fixes N] [--patience N]
vekna cast pr_fix --pull-request N --checks <text> [--remote <name>]
```

- [`cover_diff`](cover_diff.py) closes the coverage gap on the current
  branch: measure with `mise run test:py:cov:diff`, hand the uncovered lines to
  an agent, measure again.
- [`review`](review.py) reads the diff this branch adds and
  returns findings under a schema. Its agent is read-only, enforced by the
  allowlist rather than asked for in the prompt. Cabinet's own is
  `cabinet:review`.
- [`merge_ready`](merge_ready.py) runs both gates at once and babysits them to
  green. Whichever went red picks the payload shape the repair step receives.
- [`triage`](triage.py) reads a GitHub issue or PR with `gh`, has an agent
  size it against this codebase, and asks you what it deserves.
- [`nap`](nap.py) sleeps N times, counting, and does nothing else: a cast to
  watch from the dashboard, stop the daemon under, or kill and `--continue`,
  without paying an agent.
- [`tree`](tree.py) runs in a pooled worktree and returns its root and
  branch; `--dirty true` leaves an untracked file, so the tree is left
  blocked. Start it with `c` from the dashboard: a cast typed in a shell runs
  where it was typed.
- [`sweep`](sweep.py) is the factory in three rituals. It lists the open pull
  requests against the base branch, queues one `ci_watch` for each, and ends.
  Forks are not queued. The base branch comes from `[defaults.sweep]` in
  `.vekna.toml`. Needs the daemon: start it from the dashboard.
- [`ci_watch`](ci_watch.py) reads one pull request's CI under a timeout. When
  CI is red it waits on a `pr_fix`, giving up its process slot while it
  waits, then reads CI again. A fix not pushed ends it with the reason; a
  failed fix cast, a timeout or a broken `gh` end in a `Failure` step that
  reports why.
- [`pr_fix`](pr_fix.py) is the only one with `worktree=True`. It refuses a
  fork, whose branch is a stranger's code, then checks the branch out in a
  leased tree, has an allowlisted agent fix it, and asks you before it
  pushes. The push remote comes from `[defaults.pr_fix]`. Attach to it to
  answer the push.

Every one of them holds to the same bargain. The agent works permissively
inside its step — it edits files and runs commands without stopping for
permission, unless a call's `CodingOpts` names `gate_tools` — and it can put a
question to you mid-step through `ask_human`, which every `coding` call
offers. What happens next is decided at the step boundary: a gate passes or it
does not, a budget runs out, you answer a `decide`. Agents are
non-deterministic inside a step and deterministic between them.

Concurrency lives inside a step too, and needs nothing from the engine: see
[`merge_ready.quality_gates`](merge_ready.py), which starts two shells in an
`asyncio.TaskGroup` and waits for both. Each opens its own rite, because a
Task copies the contextvar the runtime hangs them from.

## Layout

One module per ritual, and its models, steps, helpers and prompt text stay
together in it — the prompts at the top, since a block of prose between two
steps hides what the steps do. [`shared.py`](shared.py) holds what more than
one ritual uses.

`__init__.py` is empty and stays that way — the engine sweeps every submodule,
so nothing needs re-exporting to be found.
