# vekna

Overseer for multiple Claude Code (or any coding agent) instances running in
tmux. One agent calls `vekna notify` → tmux jumps to its pane.

## Requires

- Python 3.14+
- `tmux` installed

## Install

```bash
pip install .
```

## Usage

Start a managed tmux session from the project you want to watch:

```bash
cd ~/projects/myapp
vekna
```

Each project directory gets its own vekna instance: the tmux socket,
tmux session, and Unix socket are all named after the current working
directory (`vekna-<basename>-<short-hash>`), so you can run one `vekna`
per project in parallel without them stepping on each other. Open
windows with `Ctrl-b c`, run a coding agent in each.

Configure each agent to run `vekna notify` as its notification hook. No
arguments — `vekna notify` reads `$TMUX` and `$TMUX_PANE` to figure out
which server owns the calling pane, then asks it to `select-pane` that
pane. The session jumps to whoever called.

### Claude Code configuration

Set the notification command in Claude Code settings to:

```
vekna notify
```

### Commands

| Command | Effect |
|---------|--------|
| `vekna` | Start (or reattach to) the tmux session and notification server for the current directory |
| `vekna notify` | Notify from the current pane (requires `$TMUX` and `$TMUX_PANE`) |

### tmux basics

| Keys | Action |
|------|--------|
| `Ctrl-b c` | New window |
| `Ctrl-b n` / `Ctrl-b p` | Next / previous window |
| `Ctrl-b 0-9` | Switch to window by number |
| `Ctrl-b d` | Detach from session |

## How it works

```
agent pane ──vekna notify──▶ /tmp/<stem>.sock ──▶ ServerMill ──▶ tmux select-pane
```

- `vekna` derives a `<stem>` from `Path.cwd()` — `vekna-<basename>-<hash>`
  — ensures the tmux session exists, binds `/tmp/<stem>.sock`, and
  attaches the terminal.
- `vekna notify` parses `$TMUX` (`<socket_path>,<pid>,<session_id>`) to
  recover the same stem from its tmux socket name, then sends
  `{"pane_id": "$TMUX_PANE"}` to `/tmp/<stem>.sock`.
- The server validates with pydantic, calls `select-pane` via libtmux,
  replies `{"status": "ok"}`.

Stem derivation and path fan-out live in `src/vekna/specs/constants.py`.

## Architecture

GLIMPSE layering (enforced by `import-linter`):

| Layer | Role |
|-------|------|
| `pacts` | Protocols, DTOs (pydantic) |
| `specs` | Constants |
| `mills` | Business logic (`ServerMill`, `NotifyClientMill`) |
| `links` | I/O adapters (`TmuxLink`, `SocketServerLink`, `SocketClientLink`) |
| `gates` | Entry points (`ClickGate` — CLI) |
| `inits` | Wiring (`init_command`) |
| `edges` | Infra boundary |

Import rules in `pyproject.toml` under `[tool.importlinter]`.

## Development

```bash
mise run start      # dev server :8000
mise run test       # all tests
mise run check      # format + lint
```

Tooling: black, ruff (`select = ["ALL"]`), mypy strict, import-linter,
pytest, vulture, deptry, codespell, pip-audit.

## License

BSD-3-Clause. See `LICENSE`.
