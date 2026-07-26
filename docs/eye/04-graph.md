# Feature — The workflow graph, drawn

**Version:** Eye (`2.x`), unscheduled within it.

See [`../reborn/00-common.md`](../reborn/00-common.md) — inferable graph — and
[01-tui.md](01-tui.md) / [02-web.md](02-web.md), the two surfaces this lands in.

## Goal

`vekna rituals show` dumps a step graph today, read off each function's source
text. `00-common.md` is honest about what that costs: a `goto` whose target is
computed rather than named does not appear, so the dump is best-effort. Drawing
a graph you know is incomplete is a weaker feature than not drawing one — the
operator cannot tell a path that does not exist from a path the parser missed.

So: make the graph total first, then render it in both surfaces, with the path
this cast actually walked lit up.

## What ships

### Declared edges (the engine part)

- **`@step(goes_to=[...])`** — optional, naming the steps this one may `goto`.
  Where it is present the engine cross-checks every actual transition against
  the declaration and raises on an undeclared edge, so the static graph is
  **exhaustive** rather than inferred, including computed targets.
- Steps without it keep today's source-text inference. `rituals show` marks
  which steps are declared and which are inferred, so "the graph is complete for
  this ritual" is a fact the operator can read rather than assume.
- `done(...)` terminals and `on_error` edges
  ([`../hand/01-failure.md`](../hand/01-failure.md)) are drawn as edges too — a
  recovery path missing from the picture is a recovery path nobody reviews.
- Unreachable steps and dead-end payloads are flagged, which is what
  `00-common.md` said static analysis could do once the graph was trustworthy.

This is small, and it is the reason the rest is worth building. It is filed here
rather than in Hand because the surfaces are the payoff; on its own it is a
better `rituals show` and little more.

### The TUI

- The graph beside the cast tree, with the walked path lit and the current step
  marked. The runtime cross-check is what makes this sound: every actual edge is
  a valid static edge, so the lit path is always a subgraph of the drawn one.
- Retreading a step (a loop) thickens the edge and shows the visit count against
  `max_visits`, which is how a ritual about to hit its budget looks before it
  hits it.
- Failed and cancelled rites are drawn as such, not omitted.

### The web view

- The same graph over the same events.
- Plus the thing the TUI cannot do: a **static** render for a ritual that is not
  running, at `/rituals/<name>` — the shape of a workflow, readable before
  anyone casts it. For a ritual someone else wrote, this is the documentation.

## Scope

- `lexicon/_mills/` — `goes_to`, the cross-check at the transition boundary.
- `lexicon/_pacts.py` — the graph model, shared by dump and both renderers so
  there is one description of a ritual's shape rather than three.
- `lexicon/_gates.py` — `rituals show` prints declared-vs-inferred.
- `gates/tui/textual/widgets/` — the graph widget.
- `gates/web/` — the graph component and the `/rituals/<name>` route.

## Out of scope

Editing the graph. "Graphical workflow editor" stays on `00-common.md`'s
not-planned list, and drawing one is not a step toward building one — rituals
are Python. Layout that rearranges itself mid-cast beyond lighting the walked
path; a graph that moves while you read it is worse than a graph that does not.
Cross-cast graphs — one graph is one ritual.

## Acceptance

- A step whose `goto` target is computed appears in `rituals show` when
  `goes_to` is declared, and does not when it is inferred — and the output says
  which case it is.
- A `goto` to a step not in `goes_to` raises, naming both steps.
- The TUI draws the graph, lights the walked path, and marks the current step;
  a loop shows its visit count.
- `on_error` edges and `done` terminals are drawn.
- An unreachable step is flagged in `rituals show` and in both renderers.
- The web view renders a ritual that has never been cast.
- `mise run check` and `mise run test` pass.
