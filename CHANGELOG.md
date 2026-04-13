# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [Unreleased] - ???

### Added

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

### Deprecated

### Removed

### Fixed

### Security


## [0.0.3] - 2026-04-13

### Added

- `vekna notify` command that signals the server to switch to the calling pane
- Asyncio unix socket server runs alongside the tmux session
- Socket client sends pane ID over `/tmp/vekna.sock`
- Window and pane switching on notification (`select-window` + `select-pane`)

### Changed

- CLI entry point renamed from `antistes` to `vekna`
- CLI restructured as a click group to support subcommands
- Tmux management rewritten with libtmux (replaces raw subprocess calls)
- `ServerMill.run()` is now async; tmux attach runs in a thread executor

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
[unreleased]: https://github.com/fancysnake/vekna/compare/v0.0.3...HEAD
[0.0.3]: https://github.com/fancysnake/vekna/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/fancysnake/vekna/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/fancysnake/vekna/releases/tag/v0.0.1