# Vekna

Vekna watches a tmux session full of running Claude Code instances and
switches focus to whichever pane needs attention. The `vekna` command
starts a server that attaches the session and listens on a Unix socket;
`vekna notify`, run from inside a pane, asks the server to select that
pane so the user lands on the agent that wants them.

## Architecture

GLIMPSE layering — see [`docs/architecture.md`](docs/architecture.md) for
the full layer map, import rules, file layout conventions, patterns, and
drift red flags.

Layer order (outermost → innermost): `edges → inits → gates → links → mills → specs → pacts`

Import boundaries are enforced by `import-linter` (`pyproject.toml`).

## Commands

```bash
mise run test       # all tests
mise run check      # format + lint
```

## Rules

- Never touch `.env*` files
- NEVER modify, create, or delete configuration files without explicit
  per-case approval.
- NEVER add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.

## Testing

### Structure

```
tests/
  unit/                   # mirrors src/ structure
  integration/
    cli/test_{command}.py
  conftest.py
```

### Unit tests (`tests/unit/`)

- Yes: mills, specs, pacts (pure logic)
- No: gates, links, inits
- Write tests in classes
- Mock at the highest level to avoid side effects
- Check all mock calls

### Integration tests (`tests/integration/`)

- Yes: CLI commands (gates)
- No: pure logic (mills, specs)
- Mock at the lowest level or don't mock if possible
- Check all mock calls and side effects

### TDD workflow

Plan -> Tests (red) -> Implement (green) -> Refactor.
Wait for approval between phases.

