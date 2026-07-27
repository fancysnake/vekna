# Reborn — Common Knowledge

Shared context for every feature. Read once; each feature doc assumes it.

## Premise

One binary, `vekna`, three roles with separate lifetimes:

- **cast process** — spawned by `vekna cast <ritual>`. Imports lexicon,
  folios, and the user's `rituals.py`. Runs one cast to completion, streams
  events to the daemon when attached, exits. Always fresh; never pooled. A
  crash kills one cast.
- **lich** (0.7.0) — long-running, named, bound to one project directory (a
  directory may hold several). Started by `vekna lich`. Runs one cast at a time
  in its directory and takes orders from
  any surface — its terminal, another shell, its own Discord channel. Spawns
  cast processes; never loads them, so it sits inside the same import rule as
  the daemon.
- **vekna daemon** — long-running, one per machine/user. Started by bare
  `vekna`. Coordinates locks, owns the durable journal, surfaces attention
  across casts, routes commands to liches. Never imports user code, lexicon, or
  folios — only the wire schema. The import boundary is enforced by
  import-linter on packages: the daemon's GLIMPSE layers may not import lexicon
  or folios, so the daemon process never loads them.

Split is structural, not policy. A misbehaving ritual or compromised SDK kills
one cast process, not the daemon or sibling casts. Blast radius = one cast. The
original soul (cross-attention surfacing) is the daemon's job, across casts.

**Staging.** 0.x builds features up. The daemon (`vekna` dashboard + real lock
coordination) arrives at **0.6.0**; before that, casts run standalone. Lock
APIs ship at **0.5.0** with a permissive default; the daemon adds coordination
and flips the default to `deny` at 0.6.0. The lich lands at **0.7.0** and is the
first release that can start work remotely. **1.0 ships when all features are
ready** (hardening), not when the daemon lands. The visual surfaces are parked
past 1.0 in [`../eye/`](../eye/README.md).

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
| **Lexicon** | SDK users `import` in `rituals.py` — `@ritual`, `@step`, `goto`/`done`, `@medium`, components. |
| **Compendium** | Runtime registry of steps, mediums, and foci inside a cast process. |
| **Grimoire** | Live tree of rite invocations for one cast. Derived, not declared. |
| **Lich** | A named, long-lived station bound to one project directory — several may share one. Runs one cast at a time, refuses a second, takes commands from any surface. Spawns cast processes; imports no ritual code. (0.7.0.) |
| **Phylactery** | A lich's row in the daemon's registry, beside `runs/`: name, root, created, last cast, Discord channel id. Outlives the process — a lich whose process died is dormant, not gone. Anything larger (session log, cast history) is the journal's already. |

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
async def fix_demo(components: FixDemo) -> Transition:
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
targets, the full **static** workflow graph is derivable without running: an
edge `A → B` exists where step `A`'s body does `goto(B, …)`, and `done(…)` is a
terminal. Execution walks one path at runtime via `goto` (recorded in the
grimoire); the static graph is the superset. `vekna rituals show` dumps it;
the dashboard renders it. The runtime cross-check guarantees every actual edge is a valid static edge,
and static analysis can flag unreachable steps or dead-end payloads. (Inference
landed with `rituals show` in 0.3.0, read off each function's source text — so
a `goto` whose target is computed rather than named does not appear, making the
dump best-effort rather than exhaustive. Rendering waits for the dashboard.)

## Process model

```
ritual library                cast process                     vekna daemon (0.6.0+)
──────────────                ────────────                     ─────────────────────
rituals.py            ◄────── imports                          ┌──── CLI
@ritual decorators                                             │
                              wire client     ────────────────►├──── locks (project, system)
                              standalone fallback              │
                              cast event log                   ├──── runs/ on disk
                              acquires/releases locks          │
                              renders prompts on stdin         ├──── lich routing (0.7.0)
                              when no daemon                   │
                                                               └──── eye surfaces (post-1.0)
```

A lich (0.7.0) hangs off the same daemon, bound to one project directory —
though a directory may hold several:

```
lich "hollow-vesper"                       ┌── the terminal that raised it
one directory            ◄── commands ─────┼── shells that attached later
one cast at a time                         └── #lich-hollow-vesper on discord
phylactery: one registry row
      │                    (the daemon routes them, keyed by lich name)
      └── spawns ──► cast process ──► reports itself to the daemon, as always
```

**Lifecycle:**

1. `vekna cast write-tests --testdir=./tests`.
2. The cast process loads `./rituals.py` (+ config modules), finds
   `@ritual('write-tests')`, validates Components against the entrypoint's
   components model, and registers its `@step`s + mediums in the compendium.
3. It probes `/tmp/vekna-<uid>.sock`. Reachable → attach + `CastHello`.
   Not → standalone (stdout events, stdin prompts).
4. It runs the ritual: the engine fires the opening transition and trampolines
   step→step on each returned `goto`, validating payloads at every boundary,
   until a step returns `done`. Steps and the mediums they call emit
   `RiteStarted`/`RiteFinished`; locks emit `LockGranted`/`LockReleased`;
   every human prompt round-trips as `DecideRequested`/`Resolved` — the single
   prompt kind (choice, tool-use approval, free text alike).
5. On disconnect or first mid-cast attach, it replays its full event log
   `GrimoireBegin` → current. The daemon rebuilds lock state from replayed lock
   events.
6. The process exits when the ritual returns or raises. It goes away.

## Package layout

```
src/vekna/
  pacts/ specs/ mills/ links/ gates/ inits/ edges/   # vekna daemon: full GLIMPSE
    gates/cli/click/                                  # vekna CLI — vekna, vekna cast
    gates/tui/textual/                                # vekna dashboard (0.7.0)

  wire/                            # wire DTOs — only schema both sides share
    __init__.py  _pacts.py        # Pydantic models, framing. Versioned independently.

  lexicon/                        # SDK — what rituals.py imports
    __init__.py                   # public: @ritual, lock, Scope, decide, ...
    _pacts.py _specs.py _mills.py _links.py _gates.py
                                  # ↑ imports vekna.wire, folio/flow, folio/shell only

  folio/                          # bundles — split-ready
    flow/    __init__.py _pacts.py _mills.py _gates.py
    shell/   __init__.py _pacts.py _mills.py _links.py _gates.py
    coding/  __init__.py _pacts.py _mills.py _gates.py
    coding_claude/ __init__.py _pacts.py _links.py   # only place importing claude-agent-sdk
    process/ lint/ lint_pylint/   # later
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
  import `vekna.wire`. (It once could import `folio.flow` / `folio.shell`; it
  no longer may, and does not.)
- `vekna.folio.<X>` MUST NOT import `vekna.folio.<Y>` (Y≠X) or vekna's GLIMPSE
  layers. MAY import `vekna.lexicon` public surface + `vekna.wire`.
- Within any package, per layer: `pacts` and `specs` import nothing internal;
  `mills` imports `pacts` + `specs`; `links` and `gates` import `pacts` only;
  `inits` binds them all. `links` and `mills` are peers — neither imports the
  other.

Enforced by 31 `import-linter` contracts; see
[`../architecture.md`](../architecture.md) for the full table.

## Wire protocol

Newline-framed JSON over Unix domain socket. Default `/tmp/vekna-<uid>.sock`
(one per user, cross-project; configurable). Pydantic DTOs live in `vekna.wire`,
defined once: both sides import them from there and neither mirrors the schema.

That is a rule about the *schema*, not about either process's imports — the
daemon's layers import `vekna.wire` and nothing else of vekna's, while a cast
process imports the lexicon, folios and the user's `rituals.py`. A `rituals.py`
never imports `vekna.wire` at all.

`wire` is versioned independently so a 0.x cast process and a later daemon share
compatible message kinds. That only holds because nothing else is built out of
these types: the grimoire has its own vocabulary (`RiteBegan` / `RiteStreamed` /
`RiteEnded` in `lexicon/_pacts`) and is projected onto the wire at the socket
edge. Until 0.6.0 writes that projection, `vekna.wire` is dormant — a designed
protocol with no consumer yet, which is deliberate.

| Kind | Direction | Notes |
|------|-----------|-------|
| `CastHello` | cast → daemon | cast_id, project_root, ritual name, Components, started_at |
| `CastGoodbye` | cast → daemon | clean exit + final status |
| `GrimoireBegin` / `GrimoireEnd` | cast → daemon | brackets a complete replay |
| `RiteStarted` / `RiteDelta` / `RiteFinished` | cast → daemon | rite lifecycle |
| `DecideRequested` / `DecideResolved` | both | every human round-trip: choice points, coding's tool-use gate, free text |
| `LockAcquireRequested` / `LockGranted` / `LockDenied` | both | colon-hierarchical keys |
| `LockReleased` | cast → daemon | tied to release token |
| `LichRose` / `LichFell` / `LichStatus` | lich → daemon | 0.7.0: name, project root, pid, idle-or-casting |
| `CastRequested` / `CastRefused` / `CastKillRequested` | surface ↔ daemon ↔ lich | 0.7.0: the daemon routes by lich name |

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

(Until 0.4.0 `@ritual` reflected loose parameters into a model via
`create_model`. A declared model is the same interface with the synthesis
removed: defaults, validators and `Field(description=...)` are now the
author's to write.)

`vekna.lexicon`:

- `File` — existing readable path. CLI tab-completes; journal stores `path + sha256`.
- `Directory` — existing path; same.
- `Text` — string, `multiline=True/False`. `--text=-` reads stdin; multiline opens `$EDITOR`.
- `Url`, `Email`, `GitRef` — Pydantic type re-exports.
- `Process`, `Executable` — **deferred to `folio/process`** (lifetime ≠ value).

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

**Implicit.** `vekna cast write-tests` walks up from `cwd` for `rituals.py`,
imports it, finds `@ritual('write-tests')`.

**Configurable.** `./.vekna.toml` (project) or `~/.config/vekna/config.toml`
(global). Both read; project wins. Env overrides for one-shots
(`VEKNA_STANDALONE_LOCKS=allow`).

```toml
[rituals]
modules = ["myproj.rituals", "myproj.dev_rituals"]
files   = ["scripts/rituals.py", "ops/rituals.py"]

[locks]
standalone = "warn"   # 0.5.0 default; flips to "deny" when the daemon lands (0.6.0)
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

One command tree. Commands arrive across releases:

```
vekna cast <ritual> [--<component>=value …]   # invoke a ritual (the only command running ritual code) — 0.2.0
vekna cast --prompt "<text>"                  # one-step cast on the coding medium, no rituals.py needed — 0.3.0
vekna rituals list                            # defined rituals + their Components — 0.3.0
vekna rituals show <ritual>                   # Component schema + inferred step graph — 0.3.0
vekna                                         # dashboard: observe running casts, drill in — 0.6.0
vekna casts                                   # list active + recent casts — 0.6.0
vekna casts resume <cast_id>                  # spawn a fresh cast process, hand it the journal — 0.6.0
vekna locks                                   # current locks + holders — 0.6.0
vekna unlock <key>                            # admin override (confirmation) — 0.6.0
vekna --debug                                 # daemon: log every event it processes — 0.6.0
vekna lich [--name=… | --new]                 # raise a lich here; detaches; asks if one sleeps — 0.7.0
vekna lich attach [<name>]                    # attach a shell to a lich's session — 0.7.0
vekna lich dismiss <name>                     # end it; archive the channel, drop the row — 0.7.0
vekna liches                                  # liches live and dormant, their roots and state — 0.7.0
vekna --help
```

Inside a lich's session — terminal, attached shell, or Discord channel — the
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

The same lore names both parked tracks: [`../eye/`](../eye/README.md), the
surfaces that watch, and [`../hand/`](../hand/README.md), the engine's acting
half — failure paths, bounds, budgets, loadable procedures. `vekna lich` needs
no skin — it is already the word.

## Dependency policy

Runtime deps: lower bounds only (`>=X.Y`), capped at next major (`<X+1`). Raise
floors only on security advisory / upstream EOL. Keeps vekna installable
alongside arbitrary project dep sets. `claude-agent-sdk` tracks latest as a
plain runtime dependency — the `coding-claude` extra was dropped in 0.3.0, so
the base wheel does pull it. Python floor 3.11 —
permissive because vekna is a dev dep elsewhere. Tooling: poetry deps, `mise
run …` commands.

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
   Standalone modes allow/warn/deny. Default `warn` at 0.5.0; flips to `deny`
   when the daemon lands (0.6.0).
7. Lock state replays from grimoire events — no separate "current state" message.
8. Always-fresh cast process per cast. No pooling. No duplicate-cast block —
   locks express it.
9. Implicit `./rituals.py` discovery; project + global config augment.
10. Daemon arrives at 0.6.0; 1.0 ships when all features are ready.
11. Standalone is a feature. Every primitive works (locks degrade per setting).
12. `folio/process` owns Process + Executable as mediums, not values.
13. A lich runs **one cast at a time and refuses a second** — no queue. Control
    commands (`status`, `log`, `kill`, decide answers) stay available while a
    cast runs and while it is blocked, so its command loop is independent of
    the cast it supervises.
14. A lich's identity lives in its phylactery — a row in the daemon's registry,
    not a store of its own — keyed by **name**, since a project root may hold
    several liches. It carries only what nothing else has: root (a dormant lich
    has no connection to learn it from, and raising one means spawning casts
    there) and Discord channel id. History stays a query over the journal,
    which costs one field on the cast record. Because a directory does not
    identify a lich, `vekna lich` where one sleeps **asks** which to raise,
    listing only the rows rooted there; `--name` and `--new` answer up front,
    so nothing scripted waits on the question.
15. Remote control arrives over **Discord**, one bot with a channel per lich —
    outbound only. Bots cannot be created programmatically; channels can. The
    platform authenticates and vekna checks an allowlist, so the daemon still
    binds nothing but its Unix socket.
16. Visual surfaces (TUI, web) are parked past 1.0 in [`../eye/`](../eye/README.md).
    They consume the same events and change no engine, so they block nothing.
    WhatsApp was dropped: it cannot give a lich a channel of its own.

## Not planned (1.0)

- Multi-Focus-per-Medium in one cast (Claude + OpenAI side-by-side). Focus swap
  supported, parallelism not.
- Network-exposed daemon (TCP, auth tokens, TLS). Unix socket on local host
  only — and Discord does not change this: the bot dials out.
- Cross-machine peer-attach.
- Graphical workflow editor. Rituals are Python.
- Pooled cast processes. Always-fresh; pool later only if cold-start hurts.
- "Block duplicate cast" mechanism. Locks already express exclusivity. (A lich
  refusing a second cast is a different thing: one station, one job.)
- Cloud-hosted runs / SaaS control plane.
- Two casts in one lich, or one lich over several project roots.
- A bot per lich. Not possible on any platform, and not needed — a channel per
  lich carries the addressing.
- Visual surfaces. Parked past 1.0, not abandoned: [`../eye/`](../eye/README.md).
- Sandboxed agent execution. Out of scope for the project, not just for 1.0 —
  the agent edits your repo on purpose. Scope the token and fence the whole
  process instead; [08-hardening.md](08-hardening.md) says how.
