# Vekna

Vekna runs coding agents as **rituals**: small Python programs whose steps the
author controls and whose agent calls happen inside those steps. `vekna cast
<ritual>` runs one; output streams live as a tree of rites. Agents run
permissively within a step; determinism lives at the step boundaries.

Python, managed by mise; poetry for dependencies; mise for tasks.

(The tmux focus-switcher vekna started as was removed in 0.3.0 — Claude Code
ships its own notifications now. `docs/reborn/` is the plan from here.)

## Commands

`mise tasks` is the source of truth for every runnable task and its
description — run it rather than trusting a hardcoded list here. Most used:

```bash
mise run test       # all tests
mise run check      # format + lint
```

## Workflow

- Consider the caller: are we torturing them? Redundant output, needless
  steps, a prompt with one possible answer — cut it.
- Don't ignore lint rules globally.
- No single-line files.
- Every major release carries a name before it carries a number — Reborn
  (`1.0.0`), Eye (`2.0.0`). Name a track when work on it starts; attach the
  number at the tag. [`docs/README.md`](docs/README.md).
- Hit friction (retried command, flaky tool, stale cache, bad error, gotcha)?
  Log it now, one or two sentences: what you did → what got in the way.

## Definition of done

Failure paths return useful errors, no silent swallows; a new path emits
meaningful events; happy path + one edge case tested; `mise run test` and
`mise run check` both green.

## Architecture

Four packages:

- `lexicon` — the engine. Ritual/step/medium model, the cast runtime, the
  grimoire, the CLI gates. `vekna.lexicon` is the ritual author's door;
  `vekna.lexicon.entry` is the CLI and cast-runtime door.
- `folio` — the mediums: `coding`, `shell`, `flow`, plus `coding_claude`, the
  Claude Agent SDK focus. Folios never import each other.
- `wire` — the daemon protocol's DTOs and framing. Imports nothing.
- `inits` — the click entry point.

Within a package, GLIMPSE layering names the roles (outermost → innermost:
`gates → links → mills → specs → pacts`):

- `gates` — CLIs, APIs, entry points
- `links` — adapters that reach the outside (processes, sockets, filesystem)
- `mills` — logic
- `specs` — business invariants: pure constants, no IO, consumed only by mills
- `pacts` — protocols, DTOs, aggregates
- `inits` — DI, top of the stack, imported by nothing

That arrow is the role ordering, **not** the import graph, which is stricter:
`gates` and `links` may import only `pacts`, and `links` and `mills` are peers
that may not import each other — `inits` joins them. `docs/architecture.md` has
the matrix, and `import-linter` is what actually decides.

Import boundaries enforced by `import-linter` (`pyproject.toml`). Full layer
map, layout, patterns, and drift flags:
[`docs/architecture.md`](docs/architecture.md).

## Rules

- Never touch `.env*` files
- NEVER add noqa/type ignore/pylint comments or directives without explicit
  per-case approval.
- `Any` reaching in from a framework object we do not define — an SDK client,
  pydantic's `ValidationError.errors()` — is accepted rather than narrowed away
  by hand. Confine it to one module and name that module in a
  `[[tool.mypy.overrides]]` entry, so the exemption cannot spread through the
  codebase; write an adapter module when the boundary has no home already.
  `vekna.folio.coding_claude._links` is the pattern.
- Functions/methods with 3+ parameters (excluding `self`) take them
  keyword-only with `*,`:

  ```python
  def fun(a: int, b: str) -> int: ...
  def fun(*, a: int, b: str, precision: int) -> int: ...
  ```

- A class that implements a `Protocol` must declare it as a base class, so the
  intent is explicit and the type checker verifies conformance. Exception: very
  generic protocols and structural callbacks where multiple unrelated
  implementations exist by duck-typing.
- `test` / `tested` is reserved for pytest; production names use `check` /
  `validation` / `verification`.
- Avoid docstrings unless unavoidable. Code self-explanatory; docstrings stale
  the day committed. In tests the Arrange-Act-Assert structure should be
  obvious from the code itself.
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

Test type follows the layer of the code under test. This holds when raising
coverage too — an uncovered line in `gates` / `links` means a missing
**integration** test, never a quick mock-everything unit test of IO-bearing
code.

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

### Mocking

- Mock external boundaries (third-party SDKs such as `claude_agent_sdk`, at
  their use site), never project code or DI.
- NEVER use `ANY` for simple values (`[]`, `{}`, booleans, strings, ints). Use
  `ANY` only for genuinely hard-to-compare objects.

## Details

- [`docs/README.md`](docs/README.md) — docs index, release names
- [`docs/architecture.md`](docs/architecture.md) — layer map, layout, patterns
- [`docs/reborn/`](docs/reborn/README.md) — Reborn (`1.0.0`), the plan from
  0.3.0 onward
- [`docs/eye/`](docs/eye/README.md) — Eye (`2.0.0`), parked until Reborn ships
- [`docs/hand/`](docs/hand/README.md) — Hand (`3.0.0`), the acting half: failure
  paths, bounds, budgets, skills, replay
- `CURRENT_TASK.md` / `PLAN.md` — the task in flight
