# PLAN — Grimoire (provider-agnostic Vekna)

This document supersedes the post-Feature-0 portions of `mvp_sdk_features.md`.
Feature 0 (CLI re-root under `vekna tmux`) proceeds as currently planned; this
plan reshapes Features 1+.

## 1. Premise

Vekna pivots from "orchestrator that runs the Claude Agent SDK" to **overseer
of many concurrent rituals**, recovering the original product soul: surfacing
the agent that needs you across many concurrent runs, one layer up from tmux
panes.

Concrete reversals from the original plan:

- The Claude Agent SDK is **one component** of **one medium** (`coding`). It
  is not the engine's primitive. Other coding components and other mediums
  are first-class citizens.
- Vekna does not run the ritual. The ritual runs in its own subprocess, in
  the project's own Python environment, and phones home to Vekna.
- The agenda is not declared. It is **derived** from the rite invocations as
  they happen — the **Grimoire** — and re-published from the start on every
  (re)attach.
- A ritual without a running Vekna is a fully usable program: events render
  to stdout, approvals prompt on stdin. Vekna is an upgrade, not a
  prerequisite.

## 2. Vocabulary

| Term         | Meaning                                                                            |
|--------------|------------------------------------------------------------------------------------|
| **Ritual**   | A workflow — async Python in `rituals.py`, decorated with `@ritual`.               |
| **Rite**     | One unit of work performed inside a ritual.                                         |
| **Medium**   | The kind of rite — a port. Typed params, declared result shape, `run()` body.      |
| **Component**| The swappable backend a medium channels — an adapter (Claude SDK, pylint, bash).   |
| **Folio**    | A bound bundle of mediums and/or components, shaped like a future standalone dist.  |
| **Lexicon**  | The SDK users `import` in `rituals.py` — the grammar of rituals.                    |
| **Compendium** | The runtime registry of mediums/components loaded inside a ritual subprocess.    |
| **Grimoire** | The live tree of rite invocations for one ritual run. Derived, not declared.       |

In short: medium ≈ port, component ≈ adapter, folio ≈ shippable bundle,
lexicon ≈ user-facing SDK, compendium ≈ in-process registry, grimoire ≈ the
agenda-as-it-happens.

## 3. Architecture

### Three roles

1. **Lexicon** — `vekna.lexicon`. The SDK users import in `rituals.py`.
   Defines `@ritual`, `@medium`, the rite-call sugar, the Grimoire event log,
   and the overseer-probe transport. Imports `folio/flow` and `folio/shell`
   (mandatory deps); nothing else from Vekna's other layers.

2. **Folios** — `vekna.folio.*`. Distributable bundles. Each folio registers
   mediums and/or components into the lexicon's compendium at import time.
   `folio/flow` and `folio/shell` ship with the base wheel; everything else
   is an extra. Folios import only the lexicon's public surface.

3. **Overseer** — `vekna.{pacts,specs,mills,links,gates,inits,edges}`. The
   passive observer. Listens on TCP, accepts ritual connections, multiplexes
   surfaces (CLI / TUI / web / WhatsApp), routes approvals and asks,
   persists runs. Imports nothing from `lexicon` or `folio`.

### Subprocess model

```
ritual subprocess                                    vekna overseer (optional)
─────────────────                                    ─────────────────────────
@ritual + @medium code   ┐                           ┌──── CLI
imports vekna.lexicon    │   /tmp/vekna-<uid>.sock   │
imports vekna.folio.*    │ ◄────── newline JSON ───► ├──── TUI
runs the rite tree       │                           │
buffers grimoire events  │                           ├──── web (later)
polls every 2s when      │                           │
  not attached           │                           ├──── WhatsApp (later)
re-publishes grimoire    │                           │
  on every (re)attach    ┘                           └──── runs/ on disk
```

### Wire protocol

Newline-framed JSON over a Unix domain socket. Default path
`/tmp/vekna-<uid>.sock` (one per user, cross-project); overridable via
config. Pydantic DTOs in `vekna.pacts.overseer` (engine side) and re-exported
through `vekna.lexicon.transport` (ritual side). Same schema, two homes,
import-linter forbids cross-imports between core and lexicon.

Unix sockets earn their keep here: filesystem-permission scoping (`0600`
keeps the socket bound to one Unix user), no port collisions, no firewall
prompts, and the existing `links/socket_*` adapters used by the tmux daemon
already speak this dialect — the overseer reuses the same plumbing. Network
exposure (TCP, auth, TLS) stays deferred.

Initial message kinds:

- `RitualHello` — run_id, project_root, ritual name, args, started_at.
- `RitualGoodbye` — clean exit with final status.
- `GrimoireBegin` — start replay (sent on every (re)attach).
- `RiteStarted`, `RiteDelta`, `RiteFinished` — rite lifecycle.
- `DecideRequested`, `DecideResolved` — flow-medium choice points.
- `ApprovalRequested`, `ApprovalResolved` — coding's tool-use gate.
- `AskRequested`, `AskResolved` — free-text or multiple-choice human input.
- `GrimoireEnd` — replay complete; live updates follow.

**Replay rule.** On every overseer attach (initial or post-disconnect) the
ritual sends `GrimoireBegin`, replays its complete event log in order, then
sends `GrimoireEnd`. The overseer wipes any cached state for that run on
`GrimoireBegin` and rebuilds from the replay. This makes the ritual the
single source of truth for its grimoire and lets a late-attached overseer
catch up without coordination.

### Probe-and-attach

The ritual is the canonical client. On startup and on every disconnect it
attempts to `connect()` the overseer's Unix socket (default
`/tmp/vekna-<uid>.sock`; configurable). Default cadence: 2s with small
jitter. Probing stops once attached and resumes if the socket closes.
Cheap; invisible.

If the probe never succeeds, the ritual runs in **standalone mode**:
events render to stdout in a structured form; `decide`, `approve`, and `ask`
prompt on stdin. The probe continues in the background; if Vekna comes up
mid-ritual, the ritual attaches and replays.

### Where components run

Components run **inside the ritual subprocess**, alongside the user's
project deps. The overseer never imports any folio or any third-party
agent/linter package. This is the rule that makes the unspoiled-core
constraint enforceable at the process boundary, not just at code-review.

## 4. Package layout

```
src/vekna/
  pacts/                          # Vekna overseer: protocols + DTOs
  specs/
  mills/                          # overseer engine: bus, runs, grimoire view
  links/                          # adapters (sockets, tmux, …)
  gates/
    cli/click/                    # vekna CLI: tmux, runs, attach
    tui/textual/                  # overseer dashboard (Feature 4)
  inits/
                                  # ↑ imports nothing below

  lexicon/                        # SDK — what rituals.py imports
    __init__.py                   # public API: @ritual, @medium, coding, shell, …
    pacts.py                      # RiteParams, RiteResult, MediumProtocol bases
    runtime.py                    # ritual driver, grimoire log, attach loop
    transport.py                  # wire protocol DTOs + framing + probe
    compendium.py                 # in-process medium/component registry
    standalone.py                 # stdout/stdin renderer when no overseer
                                  # ↑ imports folio/flow, folio/shell only

  folio/                          # bundles — split-ready
    flow/
      mediums.py                  # decide, repeat, branch, attempt, parallel
      register.py
    shell/
      mediums.py                  # shell medium + bash component
      register.py
    coding/
      pacts.py                    # CodingParams, CodingResult, CodingComponentProtocol
      mediums.py                  # coding medium
      register.py                 # registers medium (no component)
    coding_claude/
      links/claude_sdk.py         # only place importing claude-agent-sdk
      component.py                # ClaudeCodingComponent : CodingComponentProtocol
      register.py                 # registers component for the coding medium
    lint/                         # later
    lint_pylint/                  # later
                                  # ↑ each folio imports vekna.lexicon only
```

## 5. Import-linter contracts (additions)

- `vekna.{pacts,specs,mills,links,gates,inits,edges}` MUST NOT import
  `vekna.lexicon` or `vekna.folio.*` — overseer stays unspoiled.
- `vekna.lexicon` MAY import `vekna.folio.flow` and `vekna.folio.shell`;
  MUST NOT import any other folio or any overseer layer.
- `vekna.folio.<X>` MUST NOT import `vekna.folio.<Y>` for Y ≠ X — folios are
  split-ready.
- `vekna.folio.<X>` MAY import `vekna.lexicon`'s public surface
  (`vekna.lexicon` only — not `vekna.lexicon.runtime`, etc.).

These are enforced exactly the same way the existing GLIMPSE contracts are.

## 6. Extras packaging

`pyproject.toml` (preview):

```toml
[project]
dependencies = [
  "click>=8,<9",
  "pydantic>=2,<3",
  "libtmux>=0.55,<0.56",          # tmux peer-attach (still used by `vekna tmux`)
]

[project.optional-dependencies]
coding-claude = ["claude-agent-sdk>=X,<X+1"]
lint-pylint   = ["pylint>=X,<X+1"]
lint-ruff     = ["ruff>=X,<X+1"]
```

`folio/flow` and `folio/shell` need no extras — stdlib only.

`inits/rituals.py` (overseer side, not lexicon side) does no folio loading —
it only spins the daemon. Folio discovery happens in the ritual subprocess
inside `lexicon.compendium`, via explicit imports in user code or in a small
"recommended folios" auto-import in `lexicon.__init__` guarded by
`try/except ModuleNotFoundError`.

## 7. Derived Grimoire and flow mediums

The Grimoire is the tree of rite invocations as they happen. No declarative
shadow.

### Naming

- Explicit: `await coding(name="diagnose", prompt="…")`.
- Auto: `await coding(prompt="…")` becomes `coding-1`, `coding-2`, scoped per
  parent flow node. Encouraged in docs to name explicitly.

### Flow mediums (in `folio/flow`)

- `decide(name, *, outcome=None, ask=None, choices=None) -> Any` — generic
  structured choice. If `outcome=` is given, eager pass-through with a
  recorded value; otherwise resolved by the configured component (cli, tui,
  agent…). Returns whatever the choice produced (`bool`, picked string,
  etc.).
- `repeat(name, *, bound=None, until=None)` — async iterator yielding pass
  numbers; each pass becomes a child node. Warns at `bound`; can ask
  "continue?" at the boundary via the configured component.
- `branch(name, *, on, arms=None)` — multi-way dispatch, logs which arm was
  taken and why.
- `attempt(name, body)` — try/except wrapper logging the success or the
  caught exception.
- `parallel(*rites)` — concurrent fan-out (`asyncio.gather` semantics).

Raw `if`, `while`, `try` stay legal Python — they're just invisible to the
Grimoire. Convention: wrap a control-flow point in a flow medium iff a
human watching the overseer would care about that decision. Mechanical
branches stay raw.

### Sample ritual

```python
from vekna.lexicon import ritual
from vekna.folio.flow import decide, repeat
from vekna.folio.shell import shell
from vekna.folio.coding import coding   # behind extra: vekna[coding-claude]

@ritual
async def bugfix(issue_url: str) -> None:
    diagnosis = await coding(name="diagnose", prompt=f"analyze {issue_url}")

    async for _ in repeat(name="fix-until-green", bound=5):
        await coding(name="fix", prompt=f"fix:\n{diagnosis.text}")
        lint = await shell(name="lint", cmd="mise run check")
        test = await shell(name="test", cmd="mise run test")
        if await decide(name="all-green?", outcome=lint.ok and test.ok):
            break

    await coding(name="commit", prompt="commit the fix")
```

### Grimoire rendering

Both the overseer and the standalone CLI render the tree as it builds:

```
bugfix [running]
  coding  "diagnose"                   ✓ 23s
  repeat  "fix-until-green" (bound=5)
    pass 1
      coding  "fix"                     ✓ 1m02
      shell   "lint"                    ✗ exit 1
      decide  "all-green?" → False
    pass 2 [running]
      coding  "fix"                     ⏵ streaming
```

## 8. Roadmap impact

| Original feature                       | Reshaped feature                                                                                            |
|----------------------------------------|--------------------------------------------------------------------------------------------------------------|
| 0 — CLI re-root                        | Unchanged. Continue as planned in `PLAN.md`.                                                                |
| 1 — `vekna run` minimal agent          | **Lexicon SDK + standalone rituals.** Lexicon, transport, compendium, `folio/flow`, `folio/shell`, standalone renderer. **No Claude yet.** Acceptance: `python -m my_pkg.rituals my_workflow` runs end-to-end with stdout events and stdin approvals. |
| 2 — Approval gates on the CLI          | **Overseer daemon + grimoire view.** `vekna` (no subcommand) starts the overseer, binding the user's Unix socket. Rituals attach. CLI surface renders the live grimoire and routes approvals/asks across the wire. |
| 3 — `rituals.py` DSL                   | **`folio/coding` + `folio/coding-claude`.** First non-trivial folio. `vekna run "<prompt>"` is sugar for a one-rite ritual using the `coding` medium. |
| 4 — Textual TUI                        | Overseer dashboard listing rituals across projects, drill-in to a ritual's grimoire, modal for approvals/asks. |
| 5 — Parallel                           | `parallel` ships in `folio/flow` from Feature 1. This release becomes "**multi-grimoire UI**": the dashboard handles concurrent rituals cleanly. |
| 6 — Persistence + resume               | Overseer-side journal (it already records every event for replay). Resume: overseer hands a replay log to a freshly spawned ritual subprocess. |
| 7 — Web                                 | Unchanged.                                                                                                   |
| 8 — WhatsApp                            | Unchanged.                                                                                                   |
| 9 — 1.0 hardening                       | Adds: each folio audited as standalone-extractable; entry-point migration documented.                        |

## 9. Future split path

When a folio (or the lexicon) is extracted into its own distribution:

1. Move `src/vekna/folio/<name>/` to its own repo with a new `pyproject.toml`.
2. Make `vekna.folio` a PEP 420 namespace package (no `__init__.py` in the
   `vekna/folio/` directory of the core wheel).
3. Add an entry point: `vekna.folios = "<name> = vekna.folio.<name>.register:register"`.
4. `vekna.lexicon.compendium` switches from explicit imports to
   `importlib.metadata.entry_points(group="vekna.folios")` discovery.

The same path applies to the lexicon if we ever want a tiny `vekna-lexicon`
wheel separate from the overseer. No call now.

## 10. Open / deferred

- **Multi-component-per-medium in one ritual.** Out of scope for v1 (one
  active component per medium). Replaces the original plan's "Agents other
  than Claude — fork-level change" line.
- **Network-exposed overseers** (TCP binding, auth tokens, TLS). Out of
  scope for v1; Unix-socket-on-this-host only.
- **Entry-point folio discovery.** Defer until the first folio is actually
  extracted.
- **Cross-machine ritual peer-attach.** Out of scope.
