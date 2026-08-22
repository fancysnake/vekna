# Hand — the acting half

Ideas, not a plan. One file is one release's worth of work; nothing here says
when or in what order.

Where [Eye](../eye/README.md) is the surfaces that watch, Hand is what a ritual
can *do* — and what it can be held to. The engine growing the parts a long,
unattended cast turns out to need: a way to fail without dying, bounds it cannot
outrun, procedures it can reach for instead of carrying, and a way to prove it
still works.

The name was already waiting: `vekna hand` is the acting half of the Hand/Eye
easter egg in [`../reborn/common.md`](../reborn/common.md). The Eye observes;
the Hand acts.

Shipped ones move to `../done/hand/` and stop being edited. Shared context is
[`../reborn/common.md`](../reborn/common.md).

## Where these came from

A survey of prior art, July 2026 — [Barnum](https://barnum-circus.github.io/)
(a TypeScript workflow DSL over a Rust state machine, aimed at the same PR
triage / migration / test-loop workflows) and [eve](https://eve.dev/) (Vercel's
filesystem-first framework for deployed product agents).

Neither is what vekna is: Barnum ships an engine with no operator layer at all —
no daemon, no journal, no human-in-the-loop, no arbitration between concurrent
runs — and eve is cloud-shaped, aimed at support bots and internal process
automation rather than agents working a repo on your own machine. But both had
solved things vekna's engine had not, and most of this track is those things,
rebuilt in vekna's vocabulary rather than copied. Replay is the opposite: an
idea neither of them can have, because neither keeps a journal to replay.
