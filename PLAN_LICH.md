# PLAN — Lich + Vekna

This document supersedes `PLAN_GRIMOIRE.md` and the post-Feature-0 portions of
`mvp_sdk_features.md`. Feature 0's intent — re-rooting the existing tmux CLI —
still applies, but the noun changes from `vekna` to `lich`. The package on
disk is still named `vekna`; the rename is part of v0.1.0.

## 1. Premise

The product splits into two binaries with separate lifetimes:

- **lich** — a per-cast subprocess. Imports the lexicon, folios, and the
  user's `rituals.py`. Runs one ritual to completion, streams events to vekna
  when attached, exits. Always fresh; never pooled. Crashes are containment
  events.
- **vekna** — a long-running daemon, one per machine/user. Coordinates
  project-level and system-level locks, owns the durable journal, surfaces
  attention across running liches. Never imports user code, lexicon, or
  folios — only the wire schema.

The split is structural rather than policy:

- Lich is *meant* to share vocabulary with rituals (it loads them like an
  interpreter loads a script). The "unspoiled core" argument was always about
  the long-running stable thing — that constraint now applies cleanly to vekna.
- A misbehaving ritual or compromised SDK kills only its own lich, not vekna
  or sibling liches. Blast radius is one cast.
- The original soul (cross-attention surfacing) survives as vekna's job, at
  the level it actually applies — across casts, not within them.

**Staging:** v0.x ships lich only. Vekna joins at v1.x. Lock APIs exist in
v0.x with a permissive default; vekna provides real coordination later.

## 2. Vocabulary

| Term         | Meaning                                                                          |
|--------------|----------------------------------------------------------------------------------|
| **Ritual**   | A workflow definition — async Python in `rituals.py`, decorated with `@ritual`. |
| **Cast**     | One invocation of a ritual. The unit of execution. Owns locks, has a journal.    |
| **Rite**     | One unit of work inside a cast.                                                  |
| **Medium**   | The kind of rite — typed call shape, declared value shape, `run()` body. ≈ port. |
| **Focus**    | The swappable backend a Medium channels. ≈ adapter (Claude SDK, pylint, bash).   |
| **Component**| A typed value on a ritual's interface (input today, output later). `File`, `Directory`, `Text`. |
| **Folio**    | A bound bundle of Mediums and/or Foci, shaped like a future stand-alone dist.    |
| **Lexicon**  | The SDK users `import` in `rituals.py` — the grammar of rituals.                 |
| **Compendium** | Runtime registry of Mediums/Foci inside a lich subprocess.                     |
| **Grimoire** | The live tree of rite invocations for one cast. Derived, not declared.           |

"cast" is the verb (`lich cast write-tests`). The verb-noun pair (the act of
casting → the cast) keeps the metaphor honest.

**Brand.** Vekna is the umbrella; lich is one tool inside it. Config namespace
is shared (`~/.config/vekna/`, `.vekna.toml`) — forward-compatible.

## 3. Process model

```
ritual library                lich subprocess                  vekna daemon (v1+)
──────────────                ───────────────                  ──────────────────
rituals.py            ◄────── imports                          ┌──── CLI
@ritual decorators                                             │
                              wire client     ────────────────►├──── TUI
                              standalone fallback              │
                              cast event log                   ├──── web (later)
                              acquires/releases locks          │
                              renders prompts on stdin         ├──── WhatsApp (later)
                              when no daemon                   │
                                                               ├──── locks (project, system)
                                                               │
                                                               └──── runs/ on disk
```

**Lifecycle:**

1. User runs `lich cast write-tests --testdir=./tests`.
2. Lich loads `./rituals.py` (plus any modules listed in config), finds
   `@ritual('write-tests')`, validates Components against the signature.
3. Lich probes `/tmp/vekna-<uid>.sock`. If reachable, attaches and sends
   `CastHello`. If not, runs standalone (stdout for events, stdin for prompts).
4. Lich runs the ritual to completion. Each rite emits `RiteStarted`/
   `RiteFinished` events; lock operations emit `LockGranted`/`LockReleased`;
   user prompts round-trip as `DecideRequested`/`Resolved` etc.
5. On disconnect (or first attach mid-cast), lich replays its complete event
   log from `GrimoireBegin` to current state. Lock state is rebuilt by vekna
   from the replayed `LockGranted`/`LockReleased` events — no special "current
   state" message needed.
6. Lich exits when the ritual returns or raises. The subprocess goes away.

## 4. Package layout

```
src/vekna/
  pacts/                           # vekna's GLIMPSE: protocols + DTOs (overseer-side)
  specs/
  mills/                           # vekna engine: lock manager, journal, attention
  links/                           # adapters (sockets, tmux, filesystem journal)
  gates/
    cli/click/                     # vekna CLI — `vekna`, `lich tmux`
    tui/textual/                   # vekna dashboard (v1.x)
  inits/
  edges/
                                   # ↑ imports nothing below

  wire/                            # wire DTOs — the only schema both sides share
    __init__.py                    # public: every message kind, framing helpers
    _pacts.py                      # Pydantic models, framing
    # versioned independently — ships its own version pin

  lexicon/                         # SDK — what rituals.py imports
    __init__.py                    # public: @ritual, lock, Scope, decide, ...
    _pacts.py                      # protocols, base classes
    _specs.py                      # constants (rare)
    _mills.py                      # ritual driver, grimoire log
    _links.py                      # wire client, standalone renderer
    _gates.py                      # the user-facing decorators / callables
                                   # ↑ imports vekna.wire and folio/flow, folio/shell only

  folio/                           # bundles — split-ready
    flow/
      __init__.py                  # public: decide, repeat, branch, attempt, parallel
      _pacts.py
      _mills.py
      _gates.py
    shell/
      __init__.py                  # public: shell
      _pacts.py
      _mills.py
      _links.py                    # subprocess execution
      _gates.py
    coding/
      __init__.py                  # public: coding (medium), CodingFocusProtocol
      _pacts.py
      _mills.py
      _gates.py
    coding_claude/
      __init__.py                  # public: register
      _pacts.py
      _links.py                    # only place importing claude-agent-sdk
    process/                       # later
    lint/                          # later
    lint_pylint/                   # later
                                   # ↑ each folio imports vekna.lexicon's public surface only
```

**`lich`** is a CLI entry point in `pyproject.toml` (`gates/cli/click/lich.py`),
not a separate top-level package. It's the user-facing name; the implementation
lives in vekna's gates.

## 5. Internal layering convention

### vekna (the daemon) — full GLIMPSE

Same rules as today (`docs/architecture.md`). Layers are packages, never
single files. Slicing by subdomain. Imports enforced by import-linter.

### lexicon and folios — underscored GLIMPSE-flat

Each layer is a single file with a leading underscore: `_pacts.py`,
`_specs.py`, `_mills.py`, `_links.py`, `_gates.py`. Public surface lives
exclusively in `__init__.py`, which exposes a small `__all__`. The underscore
serves three jobs:

1. **Standard Python privacy.** Reaching into `_mills` from outside the folio
   is an obvious smell that linters flag.
2. **Disambiguates from vekna's GLIMPSE layers.** `_pacts.py` (folio-internal)
   reads differently from `vekna.pacts` (real overseer layer).
3. **Forces the public contract into `__init__.py`.** Reviewers and IDEs see
   the SDK shape immediately.

**Promotion path.** When a layer outgrows one file, `_mills.py` becomes
`_mills/` (a package). Same convention; no rename, no rewrite. Architecture
doc carries this carve-out: drift red flag "*layer kept as single .py file
instead of a package*" applies to vekna's layers, not to folios or lexicon.

**`edges` doesn't apply** to lexicon or folios (no infrastructure boundary).

### Import-linter contracts

- `vekna.{pacts,specs,mills,links,gates,inits,edges}` MUST NOT import
  `vekna.lexicon`, `vekna.folio.*`, or user code.
- `vekna.{pacts,specs,mills,links,gates,inits,edges}` MAY import `vekna.wire`.
- `vekna.lexicon` MAY import `vekna.wire`, `vekna.folio.flow`,
  `vekna.folio.shell`. MUST NOT import any other folio or vekna's GLIMPSE layers.
- `vekna.folio.<X>` MUST NOT import `vekna.folio.<Y>` for Y ≠ X.
- `vekna.folio.<X>` MAY import `vekna.lexicon`'s public surface and `vekna.wire`.
- Within a folio: `_pacts → _specs → _mills → _links / _gates`, same
  directionality as vekna's GLIMPSE.

## 6. Wire protocol

Newline-framed JSON over a Unix domain socket. Default path
`/tmp/vekna-<uid>.sock` (one per user, cross-project; configurable). Pydantic
DTOs in `vekna.wire`, the only place either side imports from.

The `wire` package is **versioned independently** so a v0.x lich and a v1.x
vekna can share a wheel of compatible message kinds even if the rest moves at
different cadences.

### Message kinds

| Kind                                              | Direction       | Notes                                          |
|---------------------------------------------------|-----------------|------------------------------------------------|
| `CastHello`                                       | lich → vekna    | cast_id, project_root, ritual name, Components (validated input values), started_at |
| `CastGoodbye`                                     | lich → vekna    | clean exit with final status                    |
| `GrimoireBegin` / `GrimoireEnd`                   | lich → vekna    | brackets a complete replay                      |
| `RiteStarted` / `RiteDelta` / `RiteFinished`      | lich → vekna    | rite lifecycle                                  |
| `DecideRequested` / `DecideResolved`              | both directions | flow-medium choice points                       |
| `ApprovalRequested` / `ApprovalResolved`          | both directions | coding's tool-use gate                          |
| `AskRequested` / `AskResolved`                    | both directions | free-text or multiple-choice prompt             |
| `LockAcquireRequested` / `LockGranted` / `LockDenied` | both directions | colon-hierarchical resource keys           |
| `LockReleased`                                    | lich → vekna    | tied to release token                           |

**Replay rule.** On every (re)attach, lich sends `GrimoireBegin`, replays its
complete event log in order, then sends `GrimoireEnd`. Vekna wipes any cached
state for that cast on `GrimoireBegin` and rebuilds from the replay — including
locks, since `LockGranted`/`LockReleased` are grimoire events.

This means a vekna that comes up mid-cast learns about every lock the lich
"thinks" it holds. In `warn` mode (the v0.x default) two standalone liches may
both have "granted" themselves the same lock; vekna surfaces this as a
conflict but does not undo past damage.

## 7. Ritual definition

Rituals are pure library code. No `__main__` block, no executable bit, no
wrapper.

```python
from typing import Annotated
from pydantic import BaseModel
from vekna.lexicon import ritual, lock, Scope
from vekna.lexicon.components import File, Directory, Text
from vekna.folio.flow import decide, repeat
from vekna.folio.shell import shell
from vekna.folio.coding import coding


@ritual('write-tests')
async def write_tests(
    testdir: Directory,
    spec: File,
    notes: Annotated[Text, Text(multiline=True)] | None = None,
) -> None:
    plan = await coding(prompt=f"propose tests for {spec}", output=str)

    async with lock(Scope("project") / "edit" / "tests"):
        async for _ in repeat(name="write-until-green", bound=5):
            await coding(name="write", prompt=plan, mode="edit")
            r = await shell(name="test", cmd=f"pytest {testdir}")
            if await decide(name="green?", outcome=r.ok):
                break
```

### Components (input direction)

The `@ritual` decorator inspects the signature and builds a Pydantic model
from the Component annotations. CLI flags are derived from the model; the
TUI/web surfaces render forms from its JSON schema; the journal stores the
validated values.

Component types live in `vekna.lexicon.components`:

- `File` — existing path, readable. CLI tab-completes; journal stores `path + sha256`.
- `Directory` — existing path; same treatment.
- `Text` — string with `multiline=True/False`. `--text=-` reads stdin;
  multiline opens `$EDITOR`.
- `Url`, `Email`, `GitRef` — re-exports of Pydantic types.
- `Process`, `Executable` — **deferred to `folio/process`**. Process
  Components carry lifetime; treating them as values leaks lifetime concerns
  into the ritual body. The folio owns `attach`/`spawn` Mediums; `Pid` and
  `ExecutableSpec` stay value-typed Components.

### Components (output direction)

Inputs and outputs are both Components on a single *interface*. The output
shape is declared at the call site, not pre-baked into Medium variants:

```python
# Default: canonical agent telemetry (text, tool_calls)
r = await coding(prompt="...")

# Typed: caller declares what they want back
pid = await coding(prompt="start dev server, return PID", output=int)

# Pydantic: structured value
class ServerHandle(BaseModel):
    pid: int
    port: int

handle = await coding(prompt="...", output=ServerHandle)
```

The Medium is generic over the requested type; the agent is asked (via
tool-use or JSON mode) to produce something that validates. Failure raises;
no `.ok` field. Telemetry (session_id, tool calls, token counts) lives in the
grimoire entry — queryable from the journal, never in the typed return value.

## 8. Discovery and configuration

### Implicit

`lich cast write-tests` walks up from `cwd` looking for `rituals.py`, imports
it, finds `@ritual('write-tests')`. Default for the common case.

### Configurable

`./.vekna.toml` (project) or `~/.config/vekna/config.toml` (global) augments:

```toml
[rituals]
# Additional importable modules.
modules = ["myproj.rituals", "myproj.dev_rituals"]

# Or files (paths relative to project root).
files = ["scripts/rituals.py", "ops/rituals.py"]

[locks]
# Standalone behaviour: allow / warn / deny.
standalone = "warn"   # v0.x default; flips to "deny" in v1.x
```

Both project and global config are read; project wins on conflict.
Environment variable overrides exist for one-shots (`LICH_STANDALONE_LOCKS=allow`).

## 9. Locks

Real concurrency primitive, not a coding-mode footnote.

### Keys

Free-form strings, colon-hierarchical:

```
project
project:edit
project:edit:tests
project:edit:docs
system:claude-quota
db:vekna-prod
```

### Semantics

Intention-lock style:

- Holding `project:edit` blocks any attempt to take `project`,
  `project:edit:tests`, or `project:edit:*` (ancestors and descendants).
- Holding `project:edit:tests` blocks `project`, `project:edit`, and
  `project:edit:tests:*`. Does **not** block `project:edit:docs` — siblings
  are independent.

The overseer's lock manager is a tree; acquisition walks ancestors (any held?
deny) and descendants (any held? deny). Deterministic and cheap.

### Holder

The **cast** holds the lock. A release token authorises release. The rite
that called `acquire` is just bookkeeping — the `async with lock(...)` block
scopes the release call.

### Helper

```python
from vekna.lexicon import Scope, lock

s = Scope("project") / "edit" / "tests"
async with lock(s):
    await coding(mode="edit", prompt="...")
```

`/` builds the path; the wire still ships strings. The string form
`lock("project:edit:tests")` works too — helper is sugar.

### Standalone modes

| Mode    | Behaviour                                       | Use         |
|---------|-------------------------------------------------|-------------|
| `allow` | Locks succeed silently in standalone            | CI, scripts |
| `warn`  | Locks succeed with red banner + log line        | Interactive |
| `deny`  | Locks block with retry/quit prompt              | With vekna  |

**v0.x default: `warn`.** **v1.x default: `deny`.**

Banner appears once per cast on the first lock acquisition, not per lock —
otherwise it becomes wallpaper. Format:

```
⚠ STANDALONE MODE — LOCKS NOT COORDINATED
   This cast holds locks locally only. Concurrent liches on this
   project may corrupt each other. Start vekna for real safety.
```

When `deny` blocks the rite, the prompt is the same retry/quit shape used for
other "needs vekna" features:

```
✋ rite "fix" requested lock "project:edit"
   no overseer detected — locks require an instance.
   [r] retry · [q] quit cast
```

Retry triggers the connection probe; if vekna started in the meantime, the
lock acquires and the cast continues.

## 10. Standalone mode

A lich without vekna prints events to stdout in a structured form and prompts
on stdin for `decide`/`approve`/`ask`. The probe runs in the background; if
vekna comes up mid-cast, lich attaches and replays.

What standalone loses:

- Durable journal (events render to stdout only).
- Project- and system-level coordination (modulated by the standalone-locks
  setting).
- Cross-cast attention surfacing (only one lich's view is visible).

What standalone keeps:

- Full ritual API. Every primitive works; lock primitives degrade per setting.
- Full lexicon, full folios, full Component validation, full grimoire tree.
- Full journal *of one cast* in memory — replayed in full when vekna arrives.

## 11. CLI

### v0.x (lich only)

```
lich cast <ritual> [--<component>=value …]    # invoke a ritual
lich rituals list                              # show defined rituals + their Components
lich rituals show <ritual>                     # show Component schema, where it's defined
lich tmux …                             # the existing tmux peer-attach commands
lich --help
```

`lich cast` is the only command that runs ritual code. Everything else is
introspection or the legacy tmux feature.

### v1.x (vekna joins)

```
vekna                                   # observe running liches; drill in
vekna casts                             # list active and recent casts
vekna casts resume <cast_id>            # spawn a fresh lich, hand it the journal
vekna locks                             # show current locks and holders
vekna unlock <key>                      # admin override (with confirmation)
```

`lich cast` keeps working. If vekna is up, lich phones home. If not, lich
runs standalone.

## 12. Roadmap

### v0.x — lich only

- **0.1.0** — CLI re-root: `vekna` → `lich`, tmux moves under `lich tmux`.
  Rename the package internally; reserve `vekna` as a future entry point.
- **0.2.0** — Lexicon SDK + standalone runner. `lich cast` runs rituals from
  `./rituals.py` end-to-end. Stdout events, stdin prompts. Folios: `flow`, `shell`.
- **0.3.0** — `folio/coding` and `folio/coding_claude`. Approval round-trips
  (stdin in standalone). `lich cast "<prompt>"` sugar.
- **0.4.0** — `folio/process` (Process and Executable mediums). The dev-server
  use case lands.
- **0.5.0** — Locks API, `warn` default. Banner on first acquisition. Hierarchical
  keys, `Scope` helper. No real coordination yet — locks are honest about it.

### v1.x — vekna joins

- **1.0.0** — Vekna daemon. Project- and system-level lock manager with real
  coordination. Durable journal. CLI dashboard (`vekna` no-args). Lich gains
  attach-and-replay; lock default flips to `deny`. Cross-cast attention.
- **1.1.0** — Textual TUI as the default observation surface.
- **1.2.0** — Web view (read-only, then interactive).
- **1.3.0** — WhatsApp notifications and approvals.

### Beyond

- Multi-Focus-per-Medium in one ritual.
- TCP-bound vekna (auth, TLS).
- Cross-machine peer-attach.

## 13. Things explicitly not in v1

- **Multi-Focus-per-Medium in one ritual** (Claude + OpenAI side-by-side
  in one cast). The architecture supports a swap of the active Focus, just
  not the parallelism.
- **Network-exposed vekna** (TCP, auth tokens, TLS). v1 binds a Unix socket
  on the local host.
- **Cross-machine peer-attach.** Out of scope.
- **A graphical workflow editor.** Rituals are Python — that's the point.
- **vekna-pooled lich subprocesses.** Always-fresh in v1; pool-and-warm-start
  later only if cold-start cost actually hurts.
- **A "block duplicate cast" mechanism.** Locks express exclusivity already;
  two ways to say one thing is one too many.

## 14. Resolved decisions (consolidated)

1. **Lich is the per-cast subprocess; vekna is the long-running daemon.**
   Lich imports lexicon, folios, and user code; vekna imports neither. Blast
   radius is one cast.
2. **Vocabulary**: ritual (definition) / cast (invocation) / rite (step). "cast"
   is the verb. Brand: vekna umbrella, lich is one tool.
3. **GLIMPSE for vekna; underscored GLIMPSE-flat for lexicon and folios.**
   `_pacts.py`, `_mills.py`, etc. Public surface in `__init__.py`. Promote
   files to packages on growth.
4. **Wire DTOs in their own package** (`vekna.wire`), versioned independently.
   Single source of truth — no overseer-side mirror.
5. **Inputs and outputs are both Components on a single interface.** Input
   Components via signature → Pydantic model. Output Components declared per
   call site (`output=` parameter). Telemetry lives in the grimoire entry,
   not the return value.
6. **Locks are hierarchical** colon-keyed. Cast holds, release token authorises.
   Standalone modes: `allow` / `warn` / `deny`. v0.x default `warn`, v1.x
   default `deny`.
7. **Lock state replays from grimoire events** — no separate "current state"
   message. Mid-cast vekna attach reconstructs locks from the replay.
8. **Always-fresh subprocess** per cast. No pooling in v1. No duplicate-cast
   block — locks express it.
9. **Implicit `./rituals.py`** discovery; project (`.vekna.toml`) and global
   (`~/.config/vekna/config.toml`) config augment.
10. **v0.x lich only; v1.x vekna joins.** Lock APIs ship in v0.x with permissive
    defaults; vekna adds real coordination.
11. **Standalone mode is a feature.** Every primitive works (locks degrade per
    setting). Probe runs in the background; mid-cast attach is supported.
12. **`folio/process` owns Process and Executable** as mediums, not as values.
    Lifetime concerns live in the folio, not the ritual body.
