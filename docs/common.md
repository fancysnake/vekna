# Common knowledge

Shared context every idea issue assumes, whichever milestone holds it. Read
once. This is the only file the issues point at.

## Premise

One binary, `vekna`, two roles with separate lifetimes:

- **cast process** — spawned by `vekna cast <ritual>`. Imports lexicon,
  folios, and the user's `rituals.py`. Runs one cast to completion, streams
  events to the daemon when attached, exits. Always fresh; never pooled. A
  crash kills one cast.
- **vekna daemon** — long-running, one per machine/user. Started detached by
  the first bare `vekna`, outlives every window on it, ended by `vekna stop`.
  Coordinates locks, owns the durable journal, surfaces attention across casts,
  holds every project's casts on one socket. Never imports user code, lexicon, or
  folios — only the wire schema. The import boundary is enforced by
  import-linter on packages: the daemon's GLIMPSE layers may not import lexicon
  or folios, so the daemon process never loads them.

Split is structural, not policy. A misbehaving ritual or compromised SDK kills
one cast process, not the daemon or sibling casts. Blast radius = one cast. The
original soul (cross-attention surfacing) is the daemon's job, across casts.

**Config namespace** is `~/.config/vekna/`, `.vekna.toml`. Package on disk is
named `vekna`.

## Vocabulary

| Term       | Meaning |
|------------|---------|
| **Ritual** | Workflow **entrypoint** — `@ritual` in `rituals.py`. Owns the external Component interface (CLI in, final out) and returns the first step's payload. Not a step; no payload class names it. |
| **Step**   | One **task** in a workflow — `@step` async function. Typed input value → returns the next step's payload or `Done[T]`. Its payload class *is* its identity: one class, one step. Its return annotation names its exits, checked by mypy. Calls mediums in its body. |
| **Workflow** | The graph of steps a ritual drives, connected by transitions. Declared by each step's return annotation; walked one path at a time at runtime. |
| **Transition** | What a step returns: a payload value to continue — the engine routes it to the one step whose payload class it is — or `Done(result)` to finish. A payload is a pydantic model; `Done[T]` carries a model or `None`. Routing lives in the value; the target is named by the value's class. |
| **Cast**   | One invocation of a ritual. Unit of execution. Owns locks, has a journal. Runs in a cast process. |
| **Rite**   | One **executed node** in the grimoire — a step or medium invocation. (`step`/`medium` are authored units; a rite is one run of one.) |
| **Medium** | Kind of effect a step calls — typed call shape, declared value shape, `run()` body. ≈ port. (`shell`, `coding`, `decide`.) |
| **Focus**  | Swappable backend a Medium channels. ≈ adapter (Claude SDK, pylint, bash). |
| **Component** | What a ritual needs before it can be cast, the way a spell needs its material components. Typed value on its external interface (CLI in). `File`, `Directory`, `Text`. Declared as one field of the ritual's components model. |
| **Folio**  | Bound bundle of Mediums and/or Foci, shaped like a future stand-alone dist. |
| **Tome**   | A ritual library published as an installable package, named by `[rituals] modules`. Versioned and released like any other dependency; the project that casts from it needs nothing on disk but the config line. A folio ships mediums, a tome ships rituals. |
| **Lexicon** | SDK users `import` in `rituals.py` — `@ritual`, `@step`, `Done`, `@medium`, components. |
| **Compendium** | Runtime registry of steps, mediums, and foci inside a cast process. |
| **Grimoire** | Live tree of rite invocations for one cast. Derived, not declared. |
| **Project** | A repository, keyed by its git common dir, so every worktree of one is the same project. A directory in no repository is its own. Bare `vekna` opens on the project it was typed in. |

`cast` is the verb: `vekna cast write-tests`.

## Ritual model

A workflow is a **graph of steps**, not one imperative function:

- **`@ritual`** marks the **entrypoint** — the only thing `vekna cast` invokes.
  It owns the external Component interface (CLI flags in, final result out) and
  returns the first step's payload. It is not a step, and no payload class
  names it.
- **`@step`** marks a **task** — an async function taking one typed value and
  returning the **next step's payload**, or `Done(result)`. Its return
  annotation names every exit — `-> Fix | Done[Report]` — and is the graph:
  there is no second place for an edge to live, mypy checks every `return`
  against it, and a mis-wire fails the type check rather than a cast. Its body
  calls mediums (`shell`, `coding`, `decide`). The engine validates the
  incoming value against the step's input annotation **on entry**, raising on
  mismatch.
- **A payload class is a step's identity.** One class, one step; a step may
  take a union of several. The engine trampolines step→step — looking the
  returned value's class up to find the step that takes it, emitting "finished
  A, starting B" into the grimoire — until a step returns `Done`. Step values
  are inert data: constructing one runs nothing, so a step cannot call a step.

```python
from vekna.lexicon import Done, ritual, step
from vekna.folio.shell import shell
from vekna.folio.coding import coding

class FixDemo(BaseModel): bound: int             # the ritual's components
class Attempt(BaseModel): budget: int            # run_tests's payload
class Fix(BaseModel):     failures: str; budget: int   # claude_fix's payload
class Report(BaseModel):  fixed: bool

@ritual("fix_demo")                                # boundary: CLI in, final out
def fix_demo(components: FixDemo) -> Attempt:      # `def`: nothing to await
    return Attempt(budget=components.bound)

@step
async def run_tests(a: Attempt) -> Fix | Done[Report]:
    fails = await shell("pytest")
    if not fails:     return Done(Report(fixed=True))
    if a.budget == 0: return Done(Report(fixed=False))
    return Fix(failures=fails, budget=a.budget)

@step
async def claude_fix(f: Fix) -> Attempt:
    await coding(f"fix:\n{f.failures}")
    return Attempt(budget=f.budget - 1)
```

Routing lives in the value; the type hints are the data shapes, enforced at
each boundary, and the return hint is the edge list. `Done[T]` is generic, so a
ritual's result type is stated rather than `BaseModel | None`.

**Loop safety.** The trampoline is bounded. `@ritual(…, max_steps=N)` caps the
total transitions in a cast (default in `_specs.py`); `@step(…, max_visits=N)`
optionally caps re-entry of one step. Exceeding either raises
`StepBudgetExceededError` — a naive cycle aborts loudly instead of hanging. This
safety net is distinct from *business* bounds like `fix_demo`'s `budget`, which
a step decides for itself. Time is bounded per rite, not by the trampoline:
`timeout(…, seconds=N)` and `race(…)` in `folio/flow`, and `@step(timeout=N)`
over a whole step, cancel the work — its processes included — and a timeout
arrives as a `Failure`. A cut rite ends `cancelled`, beside `ok` and `error`.

**Failure is a transition.** A step that raises goes to the step taking
`Failure[P]`, `P` the payload that entered it, or ends the cast if none does.
The edge is read off the annotations like any other.

**Inferable graph.** Because each step declares its input type and its exits,
the workflow graph is read off the annotations: an edge `A → B` exists where
`A`'s return annotation names `B`'s payload class, and `Done[...]` is a
terminal. Execution walks one path at runtime (recorded in the grimoire).
`vekna rituals show` draws the whole graph, and it is exhaustive — a computed
target is not a thing that can exist. An exit naming a class no step takes is
the one mis-wire mypy cannot see; the library refuses to load with it, so
`list`, `show` and `cast` all stop before a cast starts.

## Process model

```text
ritual library                cast process                     vekna daemon
──────────────                ────────────                     ────────────
rituals.py            ◄────── imports                          ┌──── CLI
@ritual decorators                                             │
                              wire client     ────────────────►├──── locks (project, system)
                              standalone fallback              │
                              cast event log                   ├──── runs/ on disk
                              acquires/releases locks          │
                              renders prompts on stdin         ├──── project views
                              when no daemon                   │
                                                               └──── eye surfaces
```

**Lifecycle:**

1. `vekna cast write-tests --testdir=./tests`.
2. The cast process loads `./rituals.py` or `./rituals/` (+ config modules),
   finds `@ritual('write-tests')`, validates Components against the entrypoint's
   components model, and registers its rituals in the compendium — steps
   registered themselves, by payload class, when they were decorated.
3. It probes `$XDG_RUNTIME_DIR/vekna.sock`. Reachable → attach + `CastHello`.
   Not → standalone. Either way the cast renders to its own stdout and takes
   its prompts on its own stdin; attaching adds a listener, not an owner.
4. It runs the ritual: the engine takes the opening payload and trampolines
   step→step on each returned payload, validating it at every boundary, until
   a step returns `Done`. Steps and the mediums they call emit
   `RiteStarted`/`RiteFinished`; locks emit `LockGranted`/`LockReleased`;
   every human prompt is announced as `DecideRequested` and closed by
   `DecideResolved` — the single prompt kind (choice, tool-use approval, free
   text alike), so a surface can raise a waiting cast and then clear it.
5. On disconnect or first mid-cast attach, it replays its full event log
   `GrimoireBegin` → current. The daemon rebuilds lock state from replayed lock
   events.
6. The process exits when the ritual returns or raises. It goes away.

## Package layout

```text
src/vekna/
  pacts/ specs/ mills/ links/ gates/ inits/ edges/   # vekna daemon: full GLIMPSE
    gates/cli/click/                                  # vekna CLI — vekna, vekna cast
    gates/tui/textual/                                # vekna dashboard (Eye)

  wire/                            # wire DTOs — only schema both sides share
    __init__.py  _pacts.py        # Pydantic models, framing. Versioned independently.

  lexicon/                        # SDK — what rituals.py imports
    __init__.py                   # public: @ritual, lock, Scope, decide, ...
    _pacts.py _specs.py _mills.py _links.py _gates.py

  folio/                          # bundles — split-ready
    flow/    __init__.py _pacts.py _mills.py _gates.py
    shell/   __init__.py _pacts.py _mills.py _links.py _gates.py
    coding/  __init__.py _pacts.py _mills.py _gates.py
    coding_claude/ __init__.py _pacts.py _links.py   # only place importing claude-agent-sdk
                                  # ↑ each folio imports vekna.lexicon's public surface only
```

The `vekna cast` path imports lexicon + folios + user code; the daemon path
imports neither. Same wheel; the boundary is the import-linter contract below,
backed by the process split.

## Layering convention

**vekna daemon — full GLIMPSE.** Same rules as `docs/architecture.md`. Layers
are packages, never single files. Sliced by subdomain. Import-linter enforced.

**lexicon + folios — underscored GLIMPSE-flat.** Each layer is one file:
`_pacts.py`, `_specs.py`, `_mills.py`, `_links.py`, `_gates.py`. Public surface
only in `__init__.py` (`__all__`). Underscore: signals privacy, disambiguates
from `vekna.pacts`, forces public contract into `__init__.py`. Promotion:
`_mills.py` → `_mills/` package on growth; no rename. `edges` doesn't apply (no
infra boundary).

## Import-linter contracts

- `vekna.{pacts,specs,mills,links,gates,inits,edges}` MUST NOT import
  `vekna.lexicon`, `vekna.folio.*`, or user code. MAY import `vekna.wire`.
  The CLI therefore reaches the cast runtime by dynamic import, not statically.
- `vekna.lexicon` MUST NOT import any folio or vekna's GLIMPSE layers. MAY
  import `vekna.wire`.
- `vekna.folio.<X>` MUST NOT import `vekna.folio.<Y>` (Y≠X) or vekna's GLIMPSE
  layers. MAY import `vekna.lexicon` public surface + `vekna.wire`.
- Within any package, per layer: `pacts` and `specs` import nothing internal;
  `mills` imports `pacts` + `specs`; `links` and `gates` import `pacts` only;
  `inits` binds them all. `links` and `mills` are peers — neither imports the
  other.

[`../architecture.md`](../architecture.md) holds the full table, and
`import-linter` is what decides.

## Wire protocol

Newline-framed JSON over Unix domain socket. Default `$XDG_RUNTIME_DIR/vekna.sock`,
or `/tmp/vekna-<uid>/vekna.sock` where there is no runtime directory (one per
user, cross-project; configurable). Pydantic DTOs live in `vekna.wire`,
defined once: both sides import them from there and neither mirrors the schema.

That is a rule about the *schema*, not about either process's imports — the
daemon's layers import `vekna.wire` and nothing else of vekna's, while a cast
process imports the lexicon, folios and the user's `rituals.py`. A `rituals.py`
never imports `vekna.wire` at all.

`wire` is versioned independently so a cast process and a later daemon share
compatible message kinds. That only holds because nothing else is built out of
these types: the grimoire has its own vocabulary (`RiteBegan` / `RiteStreamed` /
`RiteEnded` in `lexicon/_pacts`) and is projected onto the wire at the socket
edge, in `lexicon/_links/daemon.py` — the only place the two vocabularies meet.

| Kind | Direction | Notes |
|------|-----------|-------|
| `CastHello` | cast → daemon | cast_id, project_root, project (git common dir), ritual name, Components, started_at |
| `CastGoodbye` | cast → daemon | clean exit + final status |
| `GrimoireBegin` / `GrimoireEnd` | cast → daemon | brackets a complete replay |
| `RiteStarted` / `RiteDelta` / `RiteFinished` | cast → daemon | rite lifecycle |
| `DecideRequested` / `DecideResolved` | both | every human round-trip: choice points, coding's tool-use gate, free text. Both flow cast → daemon: the cast keeps its own stdin and the daemon is told it is waiting, not asked to answer. The daemon → cast direction is what a takeover would use |
| `LockAcquireRequested` / `LockGranted` / `LockDenied` | both | colon-hierarchical keys |
| `LockReleased` | cast → daemon | tied to release token |
| `SurfaceHello` | surface → daemon | opens a view; replayed every live cast |
| `StopRequested` | surface → daemon | `vekna stop`; ends the daemon |
| `CastRequested` / `CastRefused` / `CastKillRequested` | surface ↔ daemon | start, refuse, end a cast |

**Replay rule.** On every (re)attach: `GrimoireBegin`, replay full log in
order, `GrimoireEnd`. The daemon wipes cached state for that cast on
`GrimoireBegin`, rebuilds from replay — including locks (lock ops are grimoire
events). A daemon coming up mid-cast learns every lock the cast thinks it holds.
In `warn` mode two standalone casts may both "hold" the same lock; the daemon
surfaces the conflict, does not undo past damage.

## Components (typed interface values)

The **entrypoint** takes exactly one parameter: a Pydantic model whose fields
are its Components, declared in the author's own source. CLI flags derive from
that model; TUI/web render forms from its JSON schema; the journal stores
validated values. A ritual that needs nothing takes `NoComponents`. Step
payloads are separate **defined value types** (plain Pydantic models) validated
at each step boundary — Components are specifically the ritual's external,
CLI-facing interface, and both boundaries reject a value of the wrong model.

`vekna.lexicon`:

- `File` — existing readable path. CLI tab-completes; journal stores `path + sha256`.
- `Directory` — existing path; same.
- `Text` — string, `multiline=True/False`. `--text=-` reads stdin; multiline
  opens `$EDITOR`.
- `Url`, `Email`, `GitRef` — Pydantic type re-exports.
- `Process`, `Executable` — deferred to `folio/process` (lifetime ≠ value).

**Output direction.** "Inputs and outputs are both Components on one
interface" is unbuilt, and reads badly against the word: an output is not
something the ritual needed in order to run. What a ritual ends with is
`Done[T]` — every step that may finish says which `T` in its return annotation,
checked as the value is built like every other boundary. An output shape is
also declared at the medium call site, not baked into Medium variants:

```python
r = await coding(prompt="...")                          # default agent telemetry
pid = await coding(prompt="start dev server, return PID", output=int)  # typed
handle = await coding(prompt="...", output=ServerHandle)               # pydantic
```

Medium is generic over requested type; the agent is asked (tool-use/JSON) to
produce something that validates. Failure raises — no `.ok` on typed returns.
Telemetry (session_id, tool calls, tokens) lives in the grimoire entry,
queryable from the journal, never in the typed return value.

## Discovery and configuration

**Implicit.** `vekna cast write-tests` walks up from `cwd` for `rituals.py` —
or a `rituals/` package, which the author may split as they like — imports it,
and finds `@ritual('write-tests')`. Every submodule of a package is swept, so
its `__init__.py` stays empty.

**Configurable.** `./.vekna.toml` (project) or `~/.config/vekna/config.toml`
(global). Both read; project wins. Env overrides for one-shots
(`VEKNA_STANDALONE_LOCKS=allow`).

```toml
[rituals]
modules = ["myproj.rituals", "myproj.dev_rituals"]
files   = ["scripts/rituals.py", "ops/rituals.py"]
```

A config that does not validate stops the command with the path and the
complaint — `[rituals]` rejects unknown keys, since a misspelt one would load
nothing and leave the next cast to fail with `no ritual named ...`. Tables
vekna does not know yet are left alone.

## Standalone mode

A cast without a daemon: structured events to stdout, stdin prompts for
`decide`. The probe runs in background; the daemon comes up
mid-cast → attach + replay.

- **Loses:** durable journal, project/system coordination (modulated by
  standalone-locks setting), cross-cast attention.
- **Keeps:** full ritual API (locks degrade per setting), full lexicon +
  folios + Component validation + grimoire tree, full in-memory journal of one
  cast (replayed when the daemon arrives).

## CLI surface

One command tree.

```text
vekna cast <ritual> [--<component>=value …]   # invoke a ritual (the only command running ritual code)
vekna cast --prompt "<text>"                  # one-step cast on the coding medium, no rituals.py needed
vekna rituals list                            # defined rituals + their Components
vekna rituals show <ritual>                   # Component schema + inferred step graph
vekna                                         # this project's dashboard; starts the daemon if none
vekna stop                                    # end the daemon; running casts rejoin the next
vekna log                                     # list active + recent casts
vekna cast --continue <cast_id>               # spawn a fresh cast process, hand it the journal
vekna --debug                                 # daemon: log every event it processes
vekna --help
```

### Hand and Eye (easter egg)

`vekna hand` and `vekna eye` are an easter egg — a hidden, themed skin over
the same two roles, nothing more. They reach the same engine but wear a
dark-magic coat: flavored wording, grimoire-styled output, ritual-toned
prompts. The Hand and Eye of Vecna lore drives the mapping:

- `vekna hand <ritual>` — the acting hand. Same role as `vekna cast`.
- `vekna eye` — the observing eye. Same role as bare `vekna` dashboard.

Hidden from `--help`. Plain `vekna cast` / `vekna` stay the documented,
unflavored surface. The exact flavor (output styling, verb choices, where the
skin diverges from the plain path) is **to be shaped** — treat this as the
intent, not a spec.

The same lore names two of the idea tracks: Eye, the surfaces that watch, and
Hand, the engine's acting half.

## Dependency policy

Runtime deps: lower bounds only (`>=X.Y`), capped at next major (`<X+1`). Raise
floors only on security advisory / upstream EOL. Keeps vekna installable
alongside arbitrary project dep sets. `claude-agent-sdk` tracks latest as a
plain runtime dependency. Python floor 3.11 — permissive because vekna is a dev
dep elsewhere. Tooling: poetry deps, `mise run …` commands.

## Resolved decisions

1. One `vekna` binary, two roles: the `vekna cast` process (imports
   lexicon/folios/user code) and the long-running daemon (imports neither).
   Blast radius = one cast.
2. Vocabulary: ritual (workflow entrypoint) / step (task) / transition (the
   next payload, or `Done`) / cast (invocation) / rite (one executed
   step-or-medium node). "cast" = verb. A workflow is a graph of steps wired by
   return annotations; a payload class is a step's identity (#103).
3. GLIMPSE for the daemon; underscored GLIMPSE-flat for lexicon + folios.
   Promote files to packages on growth.
4. Wire DTOs in own package (`vekna.wire`), versioned independently. No
   daemon-side mirror.
5. Components are the ritual's inputs, declared as one Pydantic model it takes
   as its only parameter. Output declared per call site (`output=`); an
   output-side Component is deferred. Telemetry in grimoire, not return value.
6. Locks hierarchical colon-keyed. Cast holds, release token authorises.
   Standalone modes allow/warn/deny, defaulting to `deny`.
7. Lock state replays from grimoire events — no separate "current state" message.
8. Always-fresh cast process per cast. No pooling. No duplicate-cast block —
   locks express it.
9. Implicit `./rituals.py` **or `./rituals/`** discovery; project + global
   config augment. A package is swept recursively, so how it is split is the
   author's.
10. Standalone is a feature. Every primitive works (locks degrade per setting).
11. `folio/process` owns Process + Executable as mediums, not values.
12. Remote control arrives over a channel the process **dials out** to. The
    platform authenticates and vekna checks an allowlist, so the daemon still
    binds nothing but its Unix socket.

## Not planned

- Multi-Focus-per-Medium in one cast (Claude + OpenAI side-by-side). Focus swap
  supported, parallelism not.
- Network-exposed daemon (TCP, auth tokens, TLS). Unix socket on local host
  only — and a chat channel does not change this: the bot dials out.
- Cross-machine peer-attach.
- Graphical workflow editor. Rituals are Python.
- Pooled cast processes. Always-fresh; pool later only if cold-start hurts.
- "Block duplicate cast" mechanism. Locks already express exclusivity.
- Cloud-hosted runs / SaaS control plane.
- A bot per project. Not possible on any platform, and not needed — a channel
  per project carries the addressing.
- Sandboxed agent execution. Out of scope for the project — the agent edits your
  repo on purpose. Scope the token and fence the whole process instead;
  [`../safety.md`](../safety.md) says how.
