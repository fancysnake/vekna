# Vekna

Vekna runs coding agents as **rituals**: small Python programs whose steps the
author controls and whose agent calls happen inside those steps. `vekna cast
<ritual>` runs one; output streams live as a tree of rites. Agents run
permissively within a step; determinism lives at the step boundaries.

(The tmux focus-switcher vekna started as was removed in 0.3.0 — Claude Code
ships its own notifications now. `docs/reborn/` is the plan from here.)

## Architecture

Four packages:

- `lexicon` — the engine. Ritual/step/medium model, the cast runtime, the
  grimoire, the CLI gates. `vekna.lexicon` is the ritual author's door;
  `vekna.lexicon.entry` is the CLI and cast-runtime door.
- `folio` — the mediums: `coding`, `shell`, `flow`, plus `coding_claude`, the
  Claude Agent SDK focus. Folios never import each other.
- `wire` — the daemon protocol's DTOs and framing. Imports nothing.
- `inits` — the click entry point.

Within a package, GLIMPSE layering (outermost → innermost):
`gates → links → mills → specs → pacts`

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
    cli/test_{command}.py   # driven through a CLI entry point
    folio/test_{folio}.py   # a medium end-to-end, real or stubbed backend
    test_acceptance.py      # a spec's acceptance run, not one command
  conftest.py
```

### Unit tests (`tests/unit/`)

- Yes: mills, specs, pacts (pure logic)
- No: gates, inits
- Links only when the logic is pure and the I/O is injected — a renderer
  formatting to a supplied stream, a probe taking a socket path. A link that
  reaches the network or filesystem on its own belongs in integration.
- Write tests in classes
- Mock at the highest level to avoid side effects
- Check all mock calls

### Integration tests (`tests/integration/`)

- Yes: CLI commands (gates)
- No: pure logic (mills, specs)
- Mock at the lowest level or don't mock if possible
- Check all mock calls and side effects
