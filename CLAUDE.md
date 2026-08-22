# Vekna

Vekna runs coding agents as **rituals**: ordinary Python programs whose steps the
author controls and whose agent calls happen inside those steps. `vekna cast
<ritual>` runs one; output streams live as a tree of rites. Agents run
permissively within a step; determinism lives at the step boundaries.

(The tmux focus-switcher vekna started as was removed in 0.3.0 — Claude Code
ships its own notifications now.)

## Commands

`mise tasks` is the source of truth for every runnable task and its
description.

Anything not covered by a task runs through mise: `mise exec -- poetry build -f
wheel`, `mise exec -- python -c ...`. Bare `poetry`/`python`/`pytest` are denied
by the global permission rules and will not run.

## Workflow

- Consider the caller: are we torturing them? Redundant output, needless
  steps, a prompt with one possible answer — cut it.
- Don't ignore lint rules globally.
- No single-line files.
- Every major release carries a name before it carries a number — Reborn, Eye,
  Hand. Name a track when work on it starts; attach the number at the tag.
  [`docs/README.md`](docs/README.md).
- Hit friction (retried command, flaky tool, stale cache, bad error, gotcha)?
  Log it now, one or two sentences: what you did → what got in the way.

## Definition of done

Failure paths return useful errors, no silent swallows; a new path emits
meaningful events; happy path + one edge case tested; `mise run fullcheck`
green.

## Architecture

`vekna.lexicon` is the ritual author's door; `vekna.lexicon.entry` is the CLI
and cast-runtime door. `wire` imports nothing — keep it that way, no
import-linter contract guards it.

Within a package, GLIMPSE layering names the roles, outermost → innermost:
`gates → links → mills → specs → pacts`.

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

## Details

- [`tests/CLAUDE.md`](tests/CLAUDE.md) — testing conventions, loaded when you
  work under `tests/`
- [`docs/README.md`](docs/README.md) — docs index, how the idea files work,
  release names
- [`docs/architecture.md`](docs/architecture.md) — layer map, layout, patterns
- [`docs/reborn/common.md`](docs/reborn/common.md) — shared context every idea
  file assumes: premise, vocabulary, process model, wire, CLI surface
- [`docs/reborn/`](docs/reborn/README.md) — Reborn, the pivot to rituals and
  casts
- [`docs/eye/`](docs/eye/README.md) — Eye, the surfaces that watch
- [`docs/hand/`](docs/hand/README.md) — Hand, the acting half: failure paths,
  bounds, budgets, skills, replay
- [`docs/done/`](docs/done/) — shipped ideas, filed under their track. A file
  moves here instead of gaining a status line
- `CURRENT_TASK.md` / `PLAN.md` — the task in flight
