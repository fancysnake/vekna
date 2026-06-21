# Vekna

Vekna watches a tmux session full of running Claude Code instances and
switches focus to whichever pane needs attention. The `vekna tmux` command
starts a server that attaches the session and listens on a Unix socket;
`vekna tmux notify`, run from inside a pane, asks the server to select that
pane so the user lands on the agent that wants them.

## Architecture

GLIMPSE layering. Layer order (outermost → innermost):
`edges → inits → gates → links → mills → specs → pacts`

Import boundaries enforced by `import-linter` (`pyproject.toml`). Full layer
map, layout, patterns, and drift flags:
[`docs/architecture.md`](docs/architecture.md).

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
- Functions/methods with 3+ parameters (excluding `self`) take them
  keyword-only with `*,`:

  ```python
  def fun(a: int, b: str) -> int: ...
  def fun(*, a: int, b: str, precision: int) -> int: ...
  ```

- Avoid docstrings unless unavoidable. Code self-explanatory; docstrings stale
  the day committed.
- Keep `__init__.py` empty; import each symbol from the module that defines it
  (`from vekna.mills.bus import EventBus`, not via a facade). Exceptions:
  external public-API package, or line-length pressure on the canonical path.

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
