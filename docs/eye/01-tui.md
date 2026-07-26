# Feature — Textual TUI

**Version:** Eye (`2.x`), unscheduled within it. (Was `0.7.0` while it sat in
the reborn roadmap; the lich took that slot.)

See [`../reborn/00-common.md`](../reborn/00-common.md) and
[`../reborn/06-vekna-daemon.md`](../reborn/06-vekna-daemon.md). Same wire
protocol, richer surface. Liches render here too — a station in the sidebar
with the cast it is running underneath it.

## Goal

Promote the daemon's CLI Grimoire view to a Textual dashboard: running casts
across all projects in a sidebar, drill-in to any one cast's live tree,
`decide` modals, peer-attach friendly. The default observation
surface. Concurrent casts (multiple cast processes, `parallel` rites) render
cleanly — `parallel` already ships in `folio/flow` from 0.2.0, so this is the
multi-grimoire UI.

## What ships

- Textual dashboard subscribing to the daemon's bus. Default surface for
  `vekna`.
- `--no-tui` keeps the terminal-streaming behaviour from 0.6.0.
- Layout: left = cast tree (pending / running / done) across projects; right =
  active rite's live output; bottom = status bar.
- `decide` modals. Per-rite, with a queue when several arrive at
  once (multiple concurrent casts or `parallel` rites).
- Scrollback on finished rites.
- Quit / cancel (`q` or Ctrl-C) stops the host's view gracefully; peers
  disconnect cleanly.
- Per-rite stable `rite_id` routing so concurrent streams land in the right
  panel; right pane splits into tabs/grid when concurrent rites are live.

## Scope

- `gates/tui/textual/app.py` — Textual `App` subscribing to the bus.
- `gates/tui/textual/widgets/` — tree, stream panel, modal prompts, tab/grid,
  modal queue.
- `pacts/` bus additions the TUI needs (`rite_id`, `cast_id`, byte/line deltas).
- `inits/` decides surface (CLI vs TUI) at startup.

## Out of scope

Persistence (shipped 0.6.0). Web ([02-web.md](02-web.md)). Cross-machine peers.

## Acceptance

- A 3-rite cast shows live progress; decides appear as modals; final state
  marks rites done.
- Two casts running concurrently render side-by-side; decide modals from both
  queue correctly and decisions route to the right future.
- A second `vekna` attaches a second TUI to the same live view; decides
  resolvable from either window.
- Killing the host exits peers cleanly with a "view ended" message, not a
  traceback.
- `--no-tui` keeps the old path working. TUI quits cleanly, never leaves cast
  processes behind.
