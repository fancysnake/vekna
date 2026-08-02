# Feature — CLI re-root

**Version:** `0.1.0` — **shipped, then superseded.**

> The tmux subsystem this spec re-rooted was removed during 0.3.0: Claude Code
> ships its own notifications and nothing else consumed it. `vekna tmux` and
> everything under it no longer exist. Kept as the record of how the top-level
> `vekna` command was freed.

See [00-common.md](00-common.md) for vocabulary and architecture.

## Goal

Free the top-level `vekna` command for the new product. Re-root the existing
tmux CLI under a subgroup. Same daemon, same sockets, same behaviour — only
command names move. After this, bare `vekna` and `vekna cast` are reserved for
the dashboard and ritual casting that land in later releases.

## What ships

- `vekna tmux` (attach — was bare `vekna`).
- `vekna tmux daemon`, `vekna tmux notify`, `vekna tmux status-bar`.
- Bare `vekna` (no subcommand) prints help listing `tmux` and (future) `cast` /
  `rituals` groups.
- `README.md` updated with new command names.

## Scope

- `gates/cli/click/command.py` → split the flat group into a `tmux` subgroup.
  Keep the `ClickGate` factory; have it return a `vekna` root group mounting
  `tmux`.
- `tests/integration/test_command.py` updated to the new subcommand path.
- Claude Code hook guidance in README → `vekna tmux notify --app claude --hook
  Notification`.

## Out of scope

SDK, lexicon, folios, TUI, any new surface.

## Acceptance

- `vekna tmux` attaches exactly like bare `vekna` did in `0.0.4`.
- `vekna tmux notify` works identically.
- `mise run fullcheck` passes.
