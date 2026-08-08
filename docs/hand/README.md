# Hand — `3.0.0`

The acting half. Where [Eye](../eye/README.md) is the surfaces that watch, Hand
is what a ritual can *do* — and what it can be held to.

Reborn builds the engine and the console around it. Hand is the engine growing
the parts a long, unattended cast turns out to need: a way to fail without
dying, bounds it cannot outrun, procedures it can reach for instead of carrying,
and a way to prove it still works.

The name was already waiting. [`../README.md`](../README.md) had `hand` down as
"the name waiting for a release about doing rather than seeing," and `vekna
hand` is the acting half of the Hand/Eye easter egg in
[`../reborn/00-common.md`](../reborn/00-common.md). The Eye observes; the Hand
acts.

## Contents

The order among them is not fixed, though 06 wants 02 and 03 before it. Status
for these and every other feature is in the [roadmap](../README.md#roadmap).

- [01-failure.md](01-failure.md) — failure as a transition: `on_error`, a typed
  `Failure` payload, recovery as an ordinary step.
- [02-timeout-race.md](02-timeout-race.md) — `timeout` and `race` in
  `folio/flow`, with cancellation that actually reaches the process.
- [03-budgets.md](03-budgets.md) — cast budgets in wall time and tokens, beside
  the step budgets that already exist.
- [04-skills.md](04-skills.md) — procedures a `coding` rite loads on demand
  rather than carrying in every prompt.
- [05-replay.md](05-replay.md) — replay a recorded cast against its journal and
  check the ritual still walks the same path.
- [06-process.md](06-process.md) — `folio/process`: `spawn` and `attach` as
  Mediums, so a dev server's lifetime lives in a folio rather than a ritual
  body. Reborn's `0.4.0` until it became clear that owning a process is 02 and
  03 wearing a different hat.

## Filed here, not fenced here

A track is where work is *discussed*, not a queue that has to drain in order —
the number attaches at the tag. Two of these (02, 03) are small and cost almost
nothing, and if a cast left running overnight makes either load-bearing before
`1.0`, it moves into the release that needs it and this track shrinks. That is
the same rule that let the lich take Eye's slot.

What stays here regardless is anything that changes the shape of the lexicon's
public surface. Reborn's job is to get one story finished and installable; a
second syntax landing halfway through is how that job doesn't get done.

## Where these came from

A survey of prior art, July 2026 — [Barnum](https://barnum-circus.github.io/)
(a TypeScript workflow DSL over a Rust state machine, aimed at the same PR
triage / migration / test-loop workflows) and [eve](https://eve.dev/) (Vercel's
filesystem-first framework for deployed product agents).

Neither is what vekna is: Barnum ships an engine with no operator layer at all —
no daemon, no journal, no human-in-the-loop, no arbitration between concurrent
runs — and eve is cloud-shaped, aimed at support bots and internal process
automation rather than agents working a repo on your own machine. But both had
solved things Reborn's engine had not, and 01–04 are those things, rebuilt in
vekna's vocabulary rather than copied. 05 is the opposite: an idea neither of
them can have, because neither keeps a journal to replay.
