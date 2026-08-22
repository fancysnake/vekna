# The workflow graph, drawn

See [`../reborn/common.md`](../reborn/common.md) — the inferable graph — and
[tui.md](tui.md) / [web-view.md](web-view.md), the two surfaces this lands in.

## Goal

`vekna rituals show` dumps a step graph today, read off each function's source
text, so a `goto` whose target is computed does not appear. Drawing a graph you
know is incomplete is a weaker feature than not drawing one — the operator
cannot tell a path that does not exist from a path the parser missed.

So: render the graph in both surfaces, with the path this cast actually walked
lit up, over a graph that is trustworthy. Making it trustworthy is
[`../reborn/steps-as-dtos.md`](../reborn/steps-as-dtos.md)'s job; this is the
payoff.

## What ships

### The TUI

- The graph beside the cast tree, with the walked path lit and the current step
  marked. Every actual edge is a valid static edge, so the lit path is always a
  subgraph of the drawn one.
- Retreading a step (a loop) thickens the edge and shows the visit count against
  `max_visits`, which is how a ritual about to hit its budget looks before it
  hits it.
- Failed and cancelled rites are drawn as such, not omitted.
- Recovery edges are drawn too — a recovery path missing from the picture is a
  recovery path nobody reviews.
- Unreachable steps and dead-end payloads are flagged.

### The web view

- The same graph over the same events.
- Plus the thing the TUI cannot do: a **static** render for a ritual that is not
  running, at `/rituals/<name>` — the shape of a workflow, readable before
  anyone casts it. For a ritual someone else wrote, this is the documentation.

## Scope

- `lexicon/_pacts.py` — the graph model, shared by dump and both renderers so
  there is one description of a ritual's shape rather than three.
- `gates/tui/textual/widgets/` — the graph widget.
- `gates/web/` — the graph component and the `/rituals/<name>` route.

## Out of scope

Editing the graph. "Graphical workflow editor" stays on
[`../reborn/common.md`](../reborn/common.md)'s not-planned list, and drawing one
is not a step toward building one — rituals are Python. Layout that rearranges
itself mid-cast beyond lighting the walked path; a graph that moves while you
read it is worse than a graph that does not. Cross-cast graphs — one graph is
one ritual.

## Acceptance

- The TUI draws the graph, lights the walked path, and marks the current step;
  a loop shows its visit count.
- Recovery edges and `done` terminals are drawn.
- An unreachable step is flagged in both renderers.
- The web view renders a ritual that has never been cast.
- `mise run fullcheck` passes.
