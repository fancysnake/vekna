# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [Unreleased] - ???

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security


## [0.0.4] - 2026-04-21

### Added

- **Single global daemon** — one `vekna` process now handles all sessions. The
  Unix socket lives at `/tmp/vekna-<uid>.sock` (one per OS user) instead of
  one socket per project directory.
- **`vekna daemon`** command starts the server in the foreground; useful for
  debugging or running it under a process supervisor.
- **`vekna status-bar`** command prints the pending-notification text for a
  session, intended to be called from the tmux `status-right` line so the
  count is always visible without switching panes.
- **Bundled `tmux.conf`** shipped with the package; sourced automatically when
  `vekna` creates a new session. Provides Alt-key window bindings and wires up
  the `vekna status-bar` status-right segment.
- **Session registry** in the server tracks active sessions and their pending
  notification counts.
- **`EnsureSession` hook** — the server creates a named tmux session on demand
  (with the correct `start_directory`) when `vekna` is invoked in a project.
- **`StatusBar` hook** — the server returns formatted status-bar text per
  session, including a deterministic emoji + colour badge derived from the
  session name (SHA-256 hash mod palette) so multiple sessions are visually
  distinct at a glance.
- **`on_session_visited` callback** in `SelectPaneHandler` — called when the
  user lands on a session, either by direct pane-switch or by clearing a marked
  window; triggers `ServerMill.clear_pending` to reset the notification count.
- **`session_name_for_pane()`** on `TmuxLink` — looks up which tmux session a
  given pane belongs to.
- **`App` and `Hook` str-enums** in `pacts/bus` replace raw strings throughout,
  so typos are caught at type-check time.
- **`drain()`** on `EventBus` and `EventBusProtocol` — waits for in-flight
  handlers to finish before the socket server stops.
- **`DisplayErrorHandler`** handles `Error` events by calling
  `display_message` on the tmux link, surfacing invalid-payload errors to the
  user directly in the terminal.
- **`mise run coverage`** command added for line-coverage reporting.
- `vekna notify` now accepts `--app` and `--hook` flags and reads the
  hook payload from stdin, making it suitable as a drop-in Claude Code
  hook: `echo "$CLAUDE_HOOK_DATA" | vekna notify --app claude --hook Notification`.
- Notifications carry the full hook payload to the server, so future
  handlers can act on message content.

### Changed

- `vekna` (no arguments) now ensures the daemon is running (spawning it if
  needed, waiting up to 3 s for the socket to appear), sends an `EnsureSession`
  request, then attaches to the created tmux session.
- The server runs in **daemon mode**: `run()` loops indefinitely via an
  `asyncio.Event` instead of blocking on `tmux attach`, so a single process
  can serve many concurrent sessions.
- `TmuxLink.ensure_session` now accepts `start_directory` and sources the
  bundled `tmux.conf` on creation.
- Session-aware handlers: `SelectPaneHandler` and `DisplayErrorHandler` derive
  the session name from `session_name_for_pane` instead of assuming a single
  session; `_marked_windows` is now a `dict[window_id → session_name]`.
- `MarkWindowHandler` merged into `SelectPaneHandler` — pane-switching (idle)
  and window-marking (active) are handled by the same class.
- `ClaudeNotificationHandler` publishes an `Error` event on invalid payloads
  instead of raising, and forwards `event.meta` so `DisplayErrorHandler` can
  locate the correct session.
- Activity tracking switched from `session_activity` to `client_activity`,
  which tracks keyboard input rather than pane writes.
- Status bar always shows a `vekna 💀` prefix even when no sessions are
  pending, so the segment remains visible.
- Session names in the status bar and notification counts now display the
  folder name only (e.g. `myproject`), stripping the `vekna-` prefix and hash
  suffix added internally.
- `NotifyClientMill.request()` added for synchronous request/response over the
  Unix socket; `Response` model added to `pacts/socket` as the canonical
  envelope.
- Focus switching now triggers only when the session has been idle for
  at least 3 seconds (down from 5); the threshold is tunable via
  `IDLE_THRESHOLD_SECONDS`.
- When the user is active, the originating window turns red immediately
  rather than waiting for the next poll cycle.

### Removed

- `stem_from_tmux_env()` and `paths_for()` removed from `specs/constants` —
  the single daemon socket path makes per-project path derivation unnecessary.
- `seconds_since_last_keystroke` removed from `TmuxLink` (unused after the
  `client_activity` switch).

### Fixed

- Background task cancellation on Python 3.13+ no longer raises
  `CancelledError` during shutdown.


## [0.0.3] - 2026-04-13

### Added

- `vekna notify` command that signals the server to switch to the calling pane
- Asyncio unix socket server runs alongside the tmux session
- Socket client sends pane ID over `/tmp/vekna.sock`
- Window and pane switching on notification (`select-window` + `select-pane`)
- Multi-instance support: each working directory gets its own vekna
  server, tmux session, and Unix socket, keyed on a stem derived from
  the directory name plus a short hash of the absolute path. Run
  `vekna` from any project directory and it will not collide with
  other running instances.
- Typing-aware focus: if a keystroke landed in another pane within the
  last three seconds, `vekna notify` skips `select-pane` and sets the
  tmux window attention flag instead. A periodic poll clears the flag
  once the user reaches the pane on their own.
  
### Changed

- CLI entry point renamed from `antistes` to `vekna`
- CLI restructured as a click group to support subcommands
- Tmux management rewritten with libtmux (replaces raw subprocess calls)
- `ServerMill.run()` is now async; tmux attach runs in a thread executor
- `vekna notify` now reads `$TMUX` as well as `$TMUX_PANE` and routes
  automatically to the server that owns the calling pane — the global
  Claude Code hook stays literally `vekna notify` with no arguments.
- The Unix socket path is no longer the hardcoded `/tmp/vekna.sock`;
  it is now `/tmp/vekna-<basename>-<hash>.sock`, one per project.
- Package renamed from `antistes` to `vekna` across the source tree,
  imports, entry point, and linter configs. Install and import as
  `vekna`; the old name is gone.
- Socket messages use pydantic models, giving client and server a typed
  contract in place of ad-hoc dicts.

### Removed

- `links/subprocess.py` — replaced by `links/tmux.py` using libtmux

## [0.0.2] - 2026-04-07

### Added

- CLI entry point (`vekna`) that starts or attaches to a named tmux session
- Layered architecture: gates (Click CLI), mills (server logic), links (tmux subprocess calls), pacts (protocols)
- Pre-commit hooks: ruff, mypy, bandit, pylint, pytest
- CI workflow with GitHub Actions
- Dependabot configuration for pip and GitHub Actions
- Integration and unit test scaffolding with pytest

## [0.0.1] - 2026-04-07

- initial release

<!-- Links -->
[keep a changelog]: https://keepachangelog.com/en/1.0.0/
[semantic versioning]: https://semver.org/spec/v2.0.0.html

<!-- Versions -->
[unreleased]: https://github.com/fancysnake/vekna/compare/v0.0.4...HEAD
[0.0.4]: https://github.com/fancysnake/vekna/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/fancysnake/vekna/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/fancysnake/vekna/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/fancysnake/vekna/releases/tag/v0.0.1
