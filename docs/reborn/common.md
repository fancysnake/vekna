# Common knowledge

Shared context every idea under `reborn/`, `eye/` and `hand/` assumes. Read
once. This is the only file the others point at.

## Premise

One binary, `vekna`, three roles with separate lifetimes:

- **cast process** — spawned by `vekna cast <ritual>`. Imports lexicon,
  folios, and the user's `rituals.py`. Runs one cast to completion, streams
  events to the daemon when attached, exits. Always fresh; never pooled. A
  crash kills one cast.
- **lich** — long-running, named, bound to one project directory (a directory
  may hold several). Started by `vekna lich`. Runs one cast at a time in its
  directory and takes orders from any surface — its terminal, another shell,
  its own remote channel. Spawns cast processes; never loads them, so it sits
  inside the same import rule as the daemon.
- **vekna daemon** — long-running, one per machine/user. Started by bare
  `vekna`. Coordinates locks, owns the durable journal, surfaces attention
  across casts, routes commands to liches. Never imports user code, lexicon, or
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
| **Ritual** | Workflow **entrypoint** — `@ritual` in `rituals.py`. Owns the external Component interface (CLI in, final out) and fires the opening transition into the first step. Not a step; never a `goto` target. |
| **Step**   | One **task** in a workflow — `@step` async function. Typed input value → returns a `Transition`. Enforces its input/output type hints at runtime. Calls mediums in its body. |
| **Workflow** | The graph of steps a ritual drives, connected by transitions. Shaped at runtime by `goto`/`done`, not declared up front. |
| **Transition** | What a step returns: `goto(next_step, payload)` to continue, `done(result)` to finish. Both carry a pydantic model or nothing, checked as the transition is built. Routing lives in the value; target named by direct function reference. |
| **Cast**   | One invocation of a ritual. Unit of execution. Owns locks, has a journal. Runs in a cast process. |
| **Rite**   | One **executed node** in the grimoire — a step or medium invocation. (`step`/`medium` are authored units; a rite is one run of one.) |
| **Medium** | Kind of effect a step calls — typed call shape, declared value shape, `run()` body. ≈ port. (`shell`, `coding`, `decide`.) |
| **Focus**  | Swappable backend a Medium channels. ≈ adapter (Claude SDK, pylint, bash). |
| **Component** | What a ritual needs before it can be cast, the way a spell needs its material components. Typed value on its external interface (CLI in). `File`, `Directory`, `Text`. Declared as one field of the ritual's components model. |
| **Folio**  | Bound bundle of Mediums and/or Foci, shaped like a future stand-alone dist. |
| **Tome**   | A ritual library published as an installable package, named by `[rituals] modules`. Versioned and released like any other dependency; the project that casts from it needs nothing on disk but the config line. A folio ships mediums, a tome ships rituals. |
| **Lexicon** | SDK users `import` in `rituals.py` — `@ritual`, `@step`, `goto`/`done`, `@medium`, components. |
| **Compendium** | Runtime registry of steps, mediums, and foci inside a cast process. |
| **Grimoire** | Live tree of rite invocations for one cast. Derived, not declared. |
| **Lich** | A named, long-lived station bound to one project directory — several may share one. Runs one cast at a time, refuses a second, takes commands from any surface. Spawns cast processes; imports no ritual code. |
| **Phylactery** | A lich's row in the daemon's registry, beside `runs/`: name, root, created, last cast, channel id. Outlives the process — a lich whose process died is dormant, not gone. Anything larger (session log, cast history) is the journal's already. |

`cast` is the verb: `vekna cast write-tests`.

## Ritual model

A workflow is a **graph of steps**, not one imperative function:

- **`@ritual`** marks the **entrypoint** — the only thing `vekna cast` invokes.
  It owns the external Component interface (CLI flags in, final result out) and
  fires the opening `goto` into the first step. It is not a step and is never a
  `goto` target.
- **`@step`** marks a **task** — an async function taking one typed value and
  returning a **transition** (annotated `-> Transition`; it `return`s
  `goto(...)`/`done(...)`, so the file stays lintable). Its body calls mediums
  (`shell`, `coding`, `decide`). The engine validates the incoming value against
  the step's input annotation **on entry** — so every value is checked by its
  receiving step — raising on mismatch.
- **Transitions** carry routing in the return value: `goto(next_step, payload)`
  continues, `done(result)` finishes. Targets are named by direct function
  reference. The engine trampolines step→step — emitting "finished A, starting
  B" into the grimoire and cross-checking each payload against the target step's
  input type — until a step returns `done`.

```python
from vekna.lexicon import ritual, step, goto, done, Transition
from vekna.folio.shell import shell
from vekna.folio.coding import coding

class FixDemo(BaseModel): bound: int             # the ritual's components
class Attempt(BaseModel): failures: str; budget: int
class Report(BaseModel):  fixed: bool

@ritual("fix_demo")                                # boundary: CLI in, final out
def fix_demo(components: FixDemo) -> Transition:   # `def`: nothing to await
    return goto(run_tests, Attempt(failures="", budget=components.bound))

@step
async def run_tests(a: Attempt) -> Transition:
    fails = await shell("pytest")
    if not fails:     return done(Report(fixed=True))
    if a.budget == 0: return done(Report(fixed=False))
    return goto(claude_fix, Attempt(failures=fails, budget=a.budget))

@step
async def claude_fix(a: Attempt) -> Transition:
    await coding(f"fix:\n{a.failures}")
    return goto(run_tests, Attempt(failures="", budget=a.budget - 1))
```

Routing lives in the value, not the type hint; the type hints are the data
shapes, enforced at each boundary. **Annotation-gated dispatch** (route a
payload to whichever step admits its type, so `goto(payload)` needs no named
target) is a deferred, additive layer on top of explicit `goto`.

**Loop safety.** The trampoline is bounded. `@ritual(…, max_steps=N)` caps the
total transitions in a cast (default in `_specs.py`); `@step(…, max_visits=N)`
optionally caps re-entry of one step. Exceeding either raises
`StepBudgetExceededError` — a naive cycle aborts loudly instead of hanging. This
safety net is distinct from *business* bounds like `fix_demo`'s `budget`, which
a step decides for itself.

**Inferable graph.** Because each step declares its input type and its `goto`
targets, a **static** workflow graph is derivable without running: an edge
`A → B` exists where step `A`'s body does `goto(B, …)`, and `done(…)` is a
terminal. Execution walks one path at runtime via `goto` (recorded in the
grimoire). `vekna rituals show` dumps the static graph, read off each function's
source text — so a `goto` whose target is computed rather than named does not
appear. That makes the dump best-effort rather than exhaustive, and not a
guaranteed superset of the edges a cast walks.

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
                              renders prompts on stdin         ├──── lich routing
                              when no daemon                   │
                                                               └──── eye surfaces
```

A lich hangs off the same daemon, bound to one project directory — though a
directory may hold several:

```text
lich "hollow-vesper"                       ┌── the terminal that raised it
one directory            ◄── commands ─────┼── shells that attached later
one cast at a time                         └── its own remote channel
phylactery: one registry row
      │                    (the daemon routes them, keyed by lich name)
      └── spawns ──► cast process ──► reports itself to the daemon, as always
```

**Lifecycle:**

1. `vekna cast write-tests --testdir=./tests`.
2. The cast process loads `./rituals.py` or `./rituals/` (+ config modules),
   finds `@ritual('write-tests')`, validates Components against the entrypoint's
   components model, and registers its `@step`s + mediums in the compendium.
3. It probes `$XDG_RUNTIME_DIR/vekna.sock`. Reachable → attach + `CastHello`.
   Not → standalone. Either way the cast renders to its own stdout and takes
   its prompts on its own stdin; attaching adds a listener, not an owner.
4. It runs the ritual: the engine fires the opening transition and trampolines
   step→step on each returned `goto`, validating payloads at every boundary,
   until a step returns `done`. Steps and the mediums they call emit
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
| `CastHello` | cast → daemon | cast_id, project_root, ritual name, Components, started_at |
| `CastGoodbye` | cast → daemon | clean exit + final status |
| `GrimoireBegin` / `GrimoireEnd` | cast → daemon | brackets a complete replay |
| `RiteStarted` / `RiteDelta` / `RiteFinished` | cast → daemon | rite lifecycle |
| `DecideRequested` / `DecideResolved` | both | every human round-trip: choice points, coding's tool-use gate, free text. Both flow cast → daemon: the cast keeps its own stdin and the daemon is told it is waiting, not asked to answer. The daemon → cast direction is what a takeover would use |
| `LockAcquireRequested` / `LockGranted` / `LockDenied` | both | colon-hierarchical keys |
| `LockReleased` | cast → daemon | tied to release token |
| `LichRose` / `LichFell` / `LichStatus` | lich → daemon | name, project root, pid, idle-or-casting |
| `CastRequested` / `CastRefused` / `CastKillRequested` | surface ↔ daemon ↔ lich | the daemon routes by lich name |

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
- `Process`, `Executable` — deferred to `folio/process` (lifetime ≠ value),
  which is [`../hand/budgets-and-processes.md`](../hand/budgets-and-processes.md).

**Output direction — deferred.** "Inputs and outputs are both Components on one
interface" is unbuilt, and reads badly against the word: an output is not
something the ritual needed in order to run. `done(result)` takes a pydantic
model or nothing — checked as the transition is built, like every other
boundary — but the ritual declares no output *type*, so nothing says which
model a given ritual ends with. What does ship is an output shape declared at
the medium call site, not baked into Medium variants:

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
vekna                                         # dashboard: observe running casts, drill in
vekna log                                     # list active + recent casts
vekna cast --continue <cast_id>               # spawn a fresh cast process, hand it the journal
vekna --debug                                 # daemon: log every event it processes
vekna --help
```

Inside a lich's session — terminal, attached shell, or remote channel — the
vocabulary is the same: `cast`, `prompt`, `status`, `log`, `rituals`, `kill`.
Only `cast` and `prompt` are refused while a cast is running.

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

The same lore names two of the idea tracks: [`../eye/`](../eye/README.md), the
surfaces that watch, and [`../hand/`](../hand/README.md), the engine's acting
half. `vekna lich` needs no skin — it is already the word.

## Dependency policy

Runtime deps: lower bounds only (`>=X.Y`), capped at next major (`<X+1`). Raise
floors only on security advisory / upstream EOL. Keeps vekna installable
alongside arbitrary project dep sets. `claude-agent-sdk` tracks latest as a
plain runtime dependency. Python floor 3.11 — permissive because vekna is a dev
dep elsewhere. Tooling: poetry deps, `mise run …` commands.

## Resolved decisions

1. One `vekna` binary, three roles: the `vekna cast` process (imports
   lexicon/folios/user code), the lich (spawns casts, loads none), and the
   long-running daemon (imports neither). Blast radius = one cast.
2. Vocabulary: ritual (workflow entrypoint) / step (task) / transition
   (`goto`/`done`) / cast (invocation) / rite (one executed step-or-medium
   node). "cast" = verb. A workflow is a graph of steps wired by transitions,
   shaped at runtime.
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
12. A lich runs **one cast at a time and refuses a second** — no queue. Control
    commands (`status`, `log`, `kill`, decide answers) stay available while a
    cast runs and while it is blocked, so its command loop is independent of
    the cast it supervises.
13. A lich's identity lives in its phylactery — a row in the daemon's registry,
    not a store of its own — keyed by **name**, since a project root may hold
    several liches.
14. Remote control arrives over a channel the process **dials out** to. The
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
- "Block duplicate cast" mechanism. Locks already express exclusivity. (A lich
  refusing a second cast is a different thing: one station, one job.)
- Cloud-hosted runs / SaaS control plane.
- Two casts in one lich, or one lich over several project roots.
- A bot per lich. Not possible on any platform, and not needed — a channel per
  lich carries the addressing.
- Sandboxed agent execution. Out of scope for the project — the agent edits your
  repo on purpose. Scope the token and fence the whole process instead;
  [`../safety.md`](../safety.md) says how.
