# Architecture

Vekna uses the [**GLIMPSE**](https://glimpse.fancysnake.dev/) layering model.
Import boundaries are enforced by
[`import-linter`](https://import-linter.readthedocs.io/) (contracts in
`pyproject.toml`) — 31 of them, covering both the boundaries *between* packages
and the layering *inside* each one. Every module sits in a layer and every
layer has a contract; nothing is exempt by accident.

## Packages

```text
(root)    vekna's own GLIMPSE layers — the CLI and the daemon.
lexicon   The SDK and the cast runtime: ritual/step/medium model, grimoire.
folio     The mediums — coding, shell, flow — and their foci.
wire      Daemon protocol DTOs, framing, and the run record. Imports
          nothing internal.
```

### Enforced package rules

| Package   | May NOT import                        |
|-----------|---------------------------------------|
| root      | `lexicon`, `folio`                    |
| `lexicon` | root layers, `folio`                  |
| `folio.X` | root layers, any other `folio.Y`      |
| `wire`    | *(unconstrained — see below)*         |

**No root module may import the lexicon.** `vekna` (daemon) and `vekna cast`
are one binary, so importing the CLI must never pull ritual code, folios or the
agent SDK into the long-lived daemon process. Root reaches the cast runtime by
name at call time — `inits/cli.py` imports `vekna.lexicon._inits` through
`importlib`, typed via a `Protocol` and `cast()` so it needs no mypy override.

A folio never imports another folio, and the lexicon never imports a folio: it
loads them by name and asks each to `register()` what it offers — a Focus for a
medium, and optionally a one-shot prompt entry.

`vekna.wire` has no contract of its own, and needs none: it is the one package
both sides import. It holds the schema the daemon and a cast process share over
the socket — and `RunRecord`, which they share over the filesystem for the same
reason — which is why it must stay a top-level package. A daemon that may not
import the lexicon could not reach it anywhere else.

### The lexicon's one door

`vekna.lexicon` is the whole public surface: `ritual`, `step`, `medium`,
`goto`/`done`, the component types, the errors, and the medium/focus boundary
types. There is no second door, and the cast runtime is private.

## Layers within a package

```text
pacts   Protocols, DTOs, errors, enums, constants-as-types.
specs   Business invariants — pure constants, no IO.
mills   Business logic and services.
links   I/O adapters (sockets, subprocesses, SDK clients, dynamic imports).
gates   Entry points (CLI commands).
inits   Wiring — binds the other layers together, registers handlers.
edges   Framework edge (settings, entry scripts). Outside GLIMPSE proper.
```

| Layer   | May import                        | May NOT import                     |
|---------|-----------------------------------|------------------------------------|
| `pacts` | stdlib, third-party               | any internal layer                 |
| `specs` | stdlib, third-party               | any internal layer                 |
| `mills` | pacts, specs, own submodules      | links, gates, inits, edges         |
| `links` | pacts                             | mills, specs, gates, inits, edges  |
| `gates` | pacts                             | mills, specs, links, inits, edges  |
| `inits` | pacts, specs, mills, links, gates | edges                              |

**`gates` may import only `pacts`.** This is stricter than textbook GLIMPSE,
where a gate calls a service directly. Here every layer knows only the
contracts, and `inits` binds them — so a CLI command declares what it needs as
a protocol and is handed an implementation, rather than reaching for one.

**`links` and `mills` are peers.** Neither may import the other. A link that
needs a domain object returns it (`_links/loader.py` hands back a
`RitualSource`) and `inits` does the joining.

At root, each layer additionally carries an `independence` contract, so
submodules of one layer may not import each other. The lexicon has no such
contract, which is what lets `_mills/` and `_links/` be packages whose
submodules cooperate.

## Current layout

```text
(root)
  pacts/
    casts.py     # CastView, RiteView, the Casts protocol a surface reads
    routing.py   # the Surface protocol, Routed, SocketPathError
    screen.py    # the Screen protocol a surface paints on
  specs/         # empty
  mills/
    hub.py       # the daemon's model: views per cast, fan-out, replay
    debug.py     # one Routed, one line
  links/
    socket_server.py  # the Unix socket, and Serving, which closes it whole
    journal.py        # runs/<cast_id>/: run.json + events.jsonl
    terminal.py       # the daemon's own screen and keys
    debug_log.py      # --debug's file
  gates/
    cli/
      screen.py   # painting: the cast list, one cast drilled into, `casts`
      dashboard.py # what the keys do — over the two protocols, nothing else
  edges/
    pytest_plugin.py  # the pytest11 entry point: one `trial` fixture
  inits/
    cli.py       # click root: the daemon, cast, rituals, casts — and the
                 # lexicon reached dynamically
rituals.py       # the rituals this project casts on itself, named by
                 # .vekna.toml so `src` is the one measured directory
lexicon/
  _pacts.py      # Ritual, Step, Transition, Channel, rite events,
                 # component types (File, Directory, Text, Url, GitRef)
  _specs.py      # DEFAULT_MAX_STEPS
  _mills/
    engine.py    # Grimoire, Compendium, FocusSlot, rite ctx, run_cast
    dispatch.py  # @step/@ritual/@medium and signature reflection
    graph.py     # AST step-graph reader for `rituals show`
    ledger.py    # what an interrupted cast already did, for `--resume`
  _links/
    standalone.py  # StandaloneRenderer, daemon socket probe
    daemon.py      # the wire client, the grimoire→wire projection, the
                   # channel that tees a prompt onto it
    resume.py      # reading a journal back for `--resume`
    loader.py      # rituals.py / rituals/ package / module loading,
                   # submodule sweep, .vekna.toml reading
  _inits.py      # main, rituals_list, rituals_show — binds the above
  _gates.py      # empty; the CLI is the root project's
  _edges.py      # empty
folio/
  coding/        # the coding medium (backend-agnostic)
    _pacts.py    # CodingOpts, CodingResult, Session, the two errors
    _mills.py    # the medium itself, plus the one-shot prompt entry
    _inits.py    # register(): expects a Focus, offers the prompt entry
  coding_claude/ # Claude Agent SDK focus for `coding`
    _pacts.py    # ClaudeOptions
    _links.py    # ClaudeCodingFocus — the only module importing the SDK
    _inits.py    # register(): binds the Focus to the `coding` medium
  shell/         # the shell medium
    _pacts.py    # ShellResult
    _links.py    # run_bash and the `shell` medium that wraps it
  flow/          # the decide medium
wire/
  _pacts.py      # message models, and the frame codec over them
  _links.py      # read_frames off a StreamReader
trial/
  _pacts.py      # recorded calls, scripted answers, the errors
  _mills.py      # the answer script (match, queue, exhaust), the recorder
  _links.py      # the doubles — they stand where a Focus and a Channel do
  _inits.py      # Trial: installs the doubles, drives run_cast/one step
```

Split a file at ~1000 lines or when two unrelated concerns create merge
friction. Never create nested folders before files exist to fill them — the
lexicon's `_mills/` and `_links/` are packages because each holds a module that
needs its own typing exemption, not for room to grow.

## Patterns

1. **Mills are I/O-free.** Only protocols and DTOs from `pacts`. No socket,
   subprocess, or filesystem calls inside a mill.
2. **Links return, they do not register.** A link that loads or fetches hands
   back a value from `pacts`; binding it to a service is `inits`' job.
3. **Inits is the only layer that knows more than one other.**
4. **DTOs use Pydantic `BaseModel`.** Boundary contracts a third party fills in
   — `FocusReply` — are `extra="forbid"`, so a misspelled field is an error
   rather than silence.
5. **Specs are constants only.** No functions, no IO, no logic.
6. **A rite is opened in exactly one place.** `_mills/engine._rite` starts it,
   swaps the `ContextVar`, and finishes it with the status the body earned.
   Steps and mediums share it so a failure is journaled either way.
7. **The grimoire speaks its own vocabulary.** `RiteBegan` / `RiteStreamed` /
   `RiteEnded` live in `lexicon/_pacts`, carry no `cast_id`, and are projected
   onto `vekna.wire` at the socket edge — so the engine's event model and the
   daemon protocol can change independently.

## Typing exemptions

`Any` that reaches in from a framework object the project does not define is
accepted rather than narrowed away by hand, and confined to one module named in
a `pyproject.toml` override so the exemption cannot spread:

- `folio.coding_claude._links` — the Claude Agent SDK's own types.
- `edges.pytest_plugin` — `@pytest.fixture`, an overloaded Any-typed decorator.
  One module, one fixture.
- `folio.coding._pacts` — pydantic's `ValidationError.errors()`, a list of
  TypedDicts whose values are `Any`, read to turn a refused `CodingOpts` into a
  sentence. A `pacts` module may import no internal layer, so the boundary has
  no adapter to live in beside it.

Two more boundaries are narrowed per line instead, being a handful of
expressions rather than a module's worth:

- `lexicon._mills.dispatch` — reflection over runtime annotations and
  `ParamSpec` signature forwarding.
- `lexicon._links.loader` — `importlib`'s `exec_module`, `vars(module)` and
  `tomllib.load` all hand back `dict[str, Any]`.

Keeping each in its own submodule is why `_mills` and `_links` are packages: a
flat module would spread the exemption over the engine and the renderer.
Everything else, including the AST reader in `_mills/graph.py`, is strict.

## The trial's two exceptions

`vekna.trial` imports the lexicon's internals — `Grimoire`, `run_cast`, the
rite `ContextVar` — because a test harness has to drive a cast. A public
cast-runtime door would also be reachable from a `rituals.py`, which is the
thing that must not happen, so a `nothing-imports-trial` contract keeps this
door one-way instead.

Its pytest plugin sits in the root `edges/` rather than in `trial/_gates.py`,
for two reasons that both had to hold. A gate may import only `pacts`, and a
fixture must build what it hands out. And pytest loads an entry-point plugin
*before* pytest-cov starts measuring, so importing anything under `vekna.trial`
at module level reports the whole lexicon as unexecuted. From `edges/`,
importing inside the fixture body, the report is right — that is what the
`PLC0415` per-file ignore on that one module buys. `vekna.edges` is the single
source excluded from `nothing-imports-trial`, and the root `edges` contract
checks direct imports only, an edge being a door to one thing.

## Lint exemption

`PLC2701` (private-name import) is ignored under `src/vekna/lexicon/**`. Every
lexicon layer is a private module, so a layer that grows into a package has no
legal way to reach its siblings: `from .._pacts import` trips `TID252`
(relative-imports) and `from vekna.lexicon._pacts import` trips `PLC2701`. The
ignore is scoped to lexicon, so a folio still may not reach past the public
door.

## Drift red flags

- A module whose name matches no layer — it will be exempt from every contract,
  which is how `_dispatch`, `_graph` and `_loader` once hid a `gates → mills`
  import that only showed up as a transitive chain
- `pacts/dtos.py`, `pacts/protocols.py`, or `pacts/errors.py` — split by
  subdomain, not by technical kind
- `common/` or `shared/` folder inside any layer
- A `mills` module importing from `links`, or the reverse — they are peers
- A `links` module that holds business logic (validation, decisions)
- A folio importing another folio, or the lexicon importing a folio
- A static `import vekna.lexicon` anywhere under the root project
- A new mypy override, or an override growing to cover a module that does not
  sit on a genuine dynamic boundary
