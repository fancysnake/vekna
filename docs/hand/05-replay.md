# Feature — Replay: checking a ritual still walks its path

**Version:** Hand (`3.x`), unscheduled within it. Requires the journal from
[`../reborn/06-vekna-daemon.md`](../reborn/06-vekna-daemon.md).

## Goal

Nothing checks that a ritual still does its job. Rituals are the product — the
thing the user writes and keeps — and they are the least verified thing in the
system: edit a step, and the only way to find out what you broke is to spend an
agent run finding out.

From `0.6.0` the journal holds every event of every cast. A recording is a
fixture. This turns the one into the other.

## What ships

- **`vekna casts replay <cast_id>`** — re-runs the ritual with the recorded
  results served in place of the foci. No agent, no network, no cost,
  deterministic. What is exercised is the part that is meant to be
  deterministic: the transitions, the payloads, the guards, the budgets.
- **A diff, not a pass/fail grunt.** Drift is reported as the first transition
  that differs, with both payloads side by side:

  ```
  drift at step 3
    recorded: goto(write_tests, Uncovered(budget=2, report="…"))
    replayed: goto(measure,     Uncovered(budget=2))
  ```

- **`--record`** on a live cast marks it as a kept fixture and copies it out of
  `runs/` into the project (`fixtures/<name>/`), so it outlives journal pruning
  and goes into git with the ritual it belongs to.
- **A pytest helper on the lexicon's public surface**, so a fixture is an
  ordinary test in an ordinary suite:

  ```python
  from vekna.lexicon import replays

  def test_cover_diff_reaches_done() -> None:
      assert replays("fixtures/cover_diff_green")
  ```

- **An unmatched call is a clean failure.** If the ritual changed shape and
  reaches a rite the recording does not have, replay stops and names the rite.
  It never falls through to the live Focus — a verification run that quietly
  spends money is a verification run nobody trusts.
- **`decide` replays too.** The recorded answer is served, so a
  human-in-the-loop ritual is verifiable without a human — which is most of the
  interesting ones.
- **Locks and budgets replay as recorded.** Lock ops are grimoire events
  already; replay reads them rather than acquiring anything, so a fixture never
  touches the daemon.

## What this checks, and what it does not

It grades the **ritual**, not the agent. Vekna's whole claim is that
determinism lives at the step boundaries; this is the test of exactly that
claim, and nothing else. Whether the agent wrote good tests is the Focus's
problem and a different kind of question — one that needs judgement, and
therefore an agent, and therefore not a fixture.

That distinction is why this is not a rubric harness. A rubric scores prose with
a model and a scale; replay asserts that a graph still walks where it walked.
The second one is cheap, exact, runnable in CI on every commit, and available to
vekna because it keeps a journal.

Naming: `test` and `tested` are pytest's here, so the command is `replay` and
the check is `verify`.

## Scope

- `mills/replay/` — the replay driver: serve recorded rite results, compare
  transitions, produce the diff.
- `links/` — journal reader, fixture export and load.
- `gates/cli/click/` — `casts replay`, `--record`.
- `lexicon/` — `replays()` on the public surface, and the seam the driver uses
  to stand in for Focus resolution. That seam is the one engine-side change:
  Focus resolution has to be substitutable, which the registry
  (`register_focus` / `resolve_focus`) mostly already makes it.

## Out of scope

Recording every cast as a fixture — opt-in, or `runs/` becomes a fixture
graveyard. Fixtures that assert on agent *text*; the recording is what it is,
and pinning prose would fail on every model update for no signal. Grading agent
output quality. Replaying across a ritual rewrite — a rewritten ritual needs a
new recording, and the unmatched-call failure is how it says so.

## Acceptance

- Cast a ritual with `--record`, edit nothing, replay: identical path, exit 0,
  no Focus is ever called (asserted by a Focus that raises if reached).
- Change a guard, replay: the diff names the first divergent transition and
  shows both payloads.
- Add a step, replay: unmatched-call failure naming the new rite, non-zero exit,
  nothing live is contacted.
- A fixture with a `decide` replays the recorded answer with no prompt on stdin.
- `replays()` works in a plain pytest run with no daemon and no network.
- A fixture in `fixtures/` survives pruning of `runs/`.
- `mise run check` and `mise run test` pass.
