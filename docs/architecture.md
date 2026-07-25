# Architecture

Vekna uses the **GLIMPSE** layering model. Import boundaries are enforced by
`import-linter` (contracts in `pyproject.toml`).

## Packages

Four top-level packages, each layered internally:

```
lexicon   The engine: ritual/step/medium model, cast runtime, grimoire, CLI.
folio     The mediums — coding, shell, flow — and their foci.
wire      Daemon protocol DTOs and framing. Imports nothing internal.
inits     Wiring: the click entry point.
```

### Enforced package rules

| Package             | May NOT import                                     |
|---------------------|----------------------------------------------------|
| `wire`              | `inits`, `lexicon`, `folio`                        |
| `lexicon`           | `inits`, `folio.coding`, `folio.coding_claude`     |
| `folio.<name>`      | `inits`, any other `folio.<name>`                  |

A folio never imports another folio. The lexicon never imports a folio: it
loads them by name and asks each to `register()` what it offers — a Focus for
a medium, and optionally a one-shot prompt entry.

### The lexicon's two doors

- `vekna.lexicon` — the ritual author's API. `ritual`, `step`, `medium`,
  `goto`, `done`, the errors, and the medium/focus boundary types.
- `vekna.lexicon.entry` — CLI and cast-runtime plumbing. `main`,
  `rituals_list`, `rituals_show`, `run_cast`, `Grimoire`, `Compendium`.
  `vekna.inits` imports this; a `rituals.py` should not need to.

## Layers within a package

```
pacts   Protocols, DTOs, errors, enums, TypedDicts.
specs   Business invariants — pure constants, no IO.
mills   Business logic and services.
links   I/O adapters (sockets, subprocesses, SDK clients).
gates   Entry points (CLI commands).
inits   Wiring — registers handlers, starts background tasks.
```

Dependencies below are enforced; the list above is purpose only.

| Layer   | May import                 | May NOT import                    |
|---------|----------------------------|-----------------------------------|
| `pacts` | stdlib, third-party        | any internal layer                |
| `specs` | pacts                      | mills, links, gates, inits        |
| `mills` | pacts, specs               | links, gates, inits               |
| `links` | pacts                      | mills, gates, inits, specs        |
| `gates` | pacts, mills               | links, inits, specs               |
| `inits` | pacts, mills, links, gates | —                                 |

The lexicon's `_gates` imports `_links` (renderer, daemon probe) — the one
documented exception, since the cast runtime *is* the wiring in a standalone
process. 0.6.0's daemon revisits this.

## Current layout

```
lexicon/
  _pacts.py      # Ritual, Step, Transition, Channel, FocusReply, errors
  _specs.py      # DEFAULT_MAX_STEPS
  _mills.py      # Grimoire, Compendium, MediumRegistry, the rite ctx, run_cast
  _dispatch.py   # @step/@ritual/@medium and signature reflection
  _graph.py      # AST step-graph reader for `rituals show`
  _loader.py     # rituals.py / module loading, .vekna.toml reading
  _links.py      # StandaloneRenderer, daemon socket probe
  _gates.py      # main, rituals_list, rituals_show
  entry.py       # the CLI door
folio/
  coding/        # the coding medium (backend-agnostic)
  coding_claude/ # Claude Agent SDK focus for `coding`
  shell/         # the shell medium
  flow/          # the decide medium
wire/
  _pacts.py      # message models
  _mills.py      # encode/decode a frame
  _links.py      # read_frames off a StreamReader
inits/
  cli.py         # click root: cast, rituals
```

Split a file at ~1000 lines or when two unrelated concerns create merge
friction. Never create nested folders before files exist to fill them.

## Patterns

1. **Mills are I/O-free.** Only protocols and DTOs from `pacts`. No socket,
   subprocess, or filesystem calls inside `mills/`.
2. **Links implement protocols from pacts.** Mills depend on the protocol,
   never the concrete link. Exception: very generic protocols (structural
   callbacks) with many duck-typed implementations.
3. **Gates call mills, not links.**
4. **DTOs use Pydantic `BaseModel`.** Boundary contracts that a third party
   fills in — `FocusReply` — are `extra="forbid"`, so a misspelled field is an
   error rather than silence.
5. **Specs are constants only.** No functions, no IO, no logic.
6. **A rite is opened in exactly one place.** `_mills._rite` starts it, swaps
   the `ContextVar`, and finishes it with the status the body earned. Steps
   and mediums share it so a failure is journaled either way.

## Typing exemptions

Two modules relax `disallow_any_expr`, each for a boundary that cannot be
expressed otherwise. Both are declared in `pyproject.toml` with the reason:

- `lexicon._dispatch` — reflection over runtime annotations and `ParamSpec`
  signature forwarding.
- `lexicon._loader` — `importlib`'s `exec_module`, `vars(module)` and
  `tomllib.load` all hand back `dict[str, Any]`.

Everything else, including the AST reader in `_graph`, is strict.

## Drift red flags

- A layer kept as a single `.py` file instead of a package (top-level only —
  the lexicon's internal layers are deliberately modules)
- `pacts/dtos.py`, `pacts/protocols.py`, or `pacts/errors.py` — split by
  subdomain, not by technical kind
- `common/` or `shared/` folder inside any layer
- A `mills/` file importing from `links/`
- A `links/` file that holds business logic (validation, decisions)
- A folio importing another folio, or the lexicon importing a folio
- A new mypy override, or an override growing to cover a module that does not
  sit on a genuine dynamic boundary
