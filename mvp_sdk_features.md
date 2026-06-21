# Vekna Pivot — Feature Roadmap

Vekna is pivoting from a tmux focus-switcher to an **overseer of concurrent
rituals**: workflows live in a project-local `rituals.py`, each ritual runs
in its own subprocess in the project's own Python environment, and Vekna is a
passive observer that surfaces whichever ritual needs the human right now.
The architecture is provider-agnostic — the Claude Agent SDK is one Focus
of one Medium, not the engine's primitive.

> **Architecture canonical doc:** `PLAN_GRIMOIRE.md` supersedes Features 1+
> in this file. Feature 0 (CLI re-root) proceeds as planned. Per-feature
> shape will be reworked when each is planned; the headers below are
> updated, the bodies of Features 4–9 may still reflect the older
> orchestrator framing until then.

Every feature below is a **separate MR and version release**, each shipping a
usable slice end-to-end. Don't let later features leak into earlier ones —
the point of small releases is that each one gets dogfooded before the next.

---

## Architectural premise (applies to all features)

- **Vekna is an overseer, not an orchestrator.** The ritual runs in its own
  subprocess in the project's own Python environment. Vekna observes via a
  Unix-socket wire protocol and multiplexes surfaces (CLI / TUI / web /
  WhatsApp). Vekna's core never imports the lexicon or any folio; the
  unspoiled-core constraint is enforced at the process boundary.
- **Single CLI group `vekna`, re-rooted.** Feature 0 moves the existing tmux
  functionality under `vekna tmux …`. Bare `vekna` becomes the overseer
  daemon (Feature 2 onward).
- **Three layers** (full detail in `PLAN_GRIMOIRE.md`):
  - **Lexicon** (`vekna.lexicon`) — the SDK users `import` in `rituals.py`.
    Defines `@ritual`, `@medium`, rite-call sugar, the Grimoire log, and
    the overseer-probe transport.
  - **Folios** (`vekna.folio.*`) — split-ready bundles of Mediums and
    Foci. `folio/flow` and `folio/shell` ship in the base wheel; the
    rest are extras (`vekna[coding-claude]`, `vekna[lint-pylint]`, …).
  - **Overseer** (`vekna.{pacts,specs,mills,links,gates,inits,edges}`) —
    GLIMPSE layers as today. Hosts the Unix socket, the surfaces, the run
    journal.
- **GLIMPSE boundaries preserved.** Overseer code fits the existing layers
  (`pacts`/`specs`/`mills`/`links`/`gates`/`inits`/`edges`). The lexicon
  and folios are sibling top-level packages with their own import-linter
  contracts; core may not import them, folios may not import each other,
  folios may import only the lexicon's public surface.
- **Wire protocol over Unix socket.** Newline-framed JSON over
  `/tmp/vekna-<uid>.sock` (one per user, cross-project; configurable).
  Pydantic DTOs. Initial messages: `RitualHello`, `GrimoireBegin`,
  `RiteStarted`/`RiteDelta`/`RiteFinished`, `DecideRequested`/`Resolved`,
  `ApprovalRequested`/`Resolved`, `AskRequested`/`Resolved`, `GrimoireEnd`,
  `RitualGoodbye`. The ritual is the canonical client; on every (re)attach
  it replays its full event log from `GrimoireBegin` to current state.
- **Standalone is a feature.** No overseer running? The ritual runs anyway —
  events render to stdout, approvals/asks prompt on stdin. Probing
  continues in the background; if Vekna comes up mid-ritual, the ritual
  attaches and replays. `python -m my_pkg.rituals my_workflow` is enough.
- **Rituals are plain async Python.** Control flow (`if`, `while`, `try`,
  early return) is the user's code. **Significant** control-flow points get
  wrapped in flow mediums (`decide`, `repeat`, `branch`, `attempt`,
  `parallel`) so they appear in the Grimoire. Mechanical branches stay raw.
- **Derived Grimoire.** The agenda is the tree of rite invocations as they
  happen, not a separately declared structure. Surfaces render the tree
  live and replay it on attach.
- **One active Focus per Medium for v1.** Multi-Focus-per-Medium in
  one ritual (Claude + OpenAI side-by-side) is deliberately deferred.
- **Approvals and asks** flow as wire round-trips: ritual emits the request,
  overseer routes to the active surface, surface answers, overseer routes
  back, ritual resolves its `asyncio.Future`. Same future-based shape as a
  single-process design, just with IPC.
- **Runs persist on the overseer side** (Feature 6) — `~/.config/vekna/runs/`
  journals every wire event. Resume hands the journal back to a freshly
  spawned ritual subprocess.

---

## Feature 0 — Re-root the CLI under `vekna tmux`

**Version:** `0.1.0`

**Goal.** Free the top-level `vekna` command for the new orchestrator.
Nothing else changes — same daemon, same sockets, same behaviour.

**What ships.**
- `vekna tmux` (attach — was `vekna`).
- `vekna tmux daemon`, `vekna tmux notify`, `vekna tmux status-bar`.
- `vekna` (no subcommand) prints help listing `tmux` and (future) `rituals`
  groups.
- `README.md` updated with the new command names.

**Scope.**
- `gates/cli/click/command.py` → split the current flat group into a
  `tmux` subgroup. Keep `ClickGate` factory; have it return a `vekna`
  root group that mounts the `tmux` subgroup.
- Integration tests in `tests/integration/test_command.py` updated to the
  new subcommand path.
- Claude Code hook guidance in README switches to
  `vekna tmux notify --app claude --hook Notification`.

**Out of scope.** SDK, DSL, TUI, any new surface.

**Acceptance.**
- `vekna tmux` attaches exactly like `vekna` did in `0.0.4`.
- `vekna tmux notify` works identically.
- `mise run check` and `mise run test` pass.

---

## Feature 1 — Lexicon SDK and standalone rituals

**Version:** `0.2.0`

**Goal.** Ship the rituals SDK as a working program **without** Vekna's
overseer and **without** any agent provider. A user installs `vekna`, writes
a `rituals.py` using `folio/shell` + `folio/flow`, runs it with
`python -m my_pkg.rituals my_workflow`, and gets a structured terminal
experience. This proves the lexicon, the Grimoire, the flow mediums, and
the standalone renderer in isolation before any agent or daemon work.

**What ships.**
- `vekna.lexicon` — `@ritual`, `@medium`, `RiteParams`, `RiteResult`,
  `RiteContext`, the Grimoire event log, the compendium registry.
- `vekna.lexicon.transport` — Pydantic wire DTOs and probe loop (probes a
  Unix socket; falls back to standalone if unreachable).
- `vekna.lexicon.standalone` — stdout structured renderer; stdin prompts
  for `decide`/`approve`/`ask`.
- `vekna.folio.flow` — `decide`, `repeat`, `branch`, `attempt`, `parallel`.
- `vekna.folio.shell` — `shell` Medium + bash Focus.
- A worked example: `examples/rituals.py` with at least one ritual using
  `shell` + `decide` + `repeat`.

**Scope.**
- New top-level packages `vekna.lexicon` and `vekna.folio` with their own
  import-linter contracts (core may not import them; folios may not import
  each other; folios may import only `vekna.lexicon`'s public surface).
- Pydantic DTOs for the wire schema in `vekna.lexicon.transport`. The
  overseer-side mirrors will be added in Feature 2; for now the schema
  lives once and the probe degrades gracefully.
- Unit tests for flow mediums; integration test for the standalone runner
  driving a small ritual end-to-end.

**Out of scope.** Overseer daemon. Coding medium. Claude. TUI.
Persistence. `vekna run "<prompt>"` sugar (lands in Feature 3).

**Acceptance.**
- `python -m examples.rituals fix_demo --bound 3` runs end-to-end, prints
  a structured Grimoire to stdout, and exits 0.
- `decide` / `approve` / `ask` prompt on stdin and route the answer back.
- Probing the absent overseer socket is silent and does not hang.
- `mise run check` and `mise run test` pass.

---

## Feature 2 — Overseer daemon and Grimoire view

**Version:** `0.3.0`

**Goal.** Stand up Vekna proper. Bare `vekna` (no subcommand) becomes the
overseer: binds the user's Unix socket, accepts ritual connections, renders
each ritual's live Grimoire to a terminal surface, routes
approvals/decides/asks across the wire. A second terminal running `vekna`
in the same user account attaches as a peer and sees the same view.

**What ships.**
- `vekna` (no subcommand) — overseer daemon. First invocation binds
  `/tmp/vekna-<uid>.sock` and renders the active rituals to the terminal;
  subsequent invocations attach as peer surfaces.
- Newline-framed JSON wire protocol mirroring the Pydantic DTOs from
  Feature 1's lexicon. Overseer-side handlers for every message kind.
- CLI Grimoire renderer: a tree view of running rituals, drill-in to one,
  prompts for `Decide` / `Approval` / `Ask` requests, response routed back
  to the originating ritual.
- Cross-project visibility: every ritual that probes the user's socket
  shows up, regardless of `cwd`.
- Clean disconnect: ritual closing the socket marks its run as ended; the
  ritual exiting un-cleanly surfaces as a clear "ritual disconnected"
  state, not a traceback.

**Scope.**
- `pacts/overseer.py` — DTOs (mirrors of `lexicon.transport`'s schema, kept
  in sync; same Pydantic models, two import locations enforced by
  import-linter).
- `mills/overseer.py` — daemon engine: tracks rituals, multiplexes
  surfaces, routes round-trips.
- `links/socket_server.py` already handles the Unix socket; extend or
  duplicate for the overseer's framing.
- `gates/cli/click/overseer.py` — terminal renderer + input loop.
- `inits/overseer.py` — wires the daemon.
- Lexicon wires its probe to actually attach (no behavioural change to
  standalone fallback).

**Out of scope.** TUI (Feature 4). Persistence (Feature 6). Coding /
Claude (Feature 3). WhatsApp (Feature 8).

**Acceptance.**
- Terminal A: `vekna` shows an empty overseer view.
- Terminal B: runs `python -m examples.rituals fix_demo` — the ritual
  appears in A within ~2s. Approvals/decides answered in A reach B.
- Terminal C: a second `vekna` attaches as a peer; sees the same view; can
  also answer prompts.
- Overseer killed: B keeps running standalone. Overseer restarted: B
  re-attaches and replays its full Grimoire from `GrimoireBegin`.

---

## Feature 3 — `folio/coding` and `folio/coding-claude`

**Version:** `0.4.0`

**Goal.** First action Medium with a real third-party Focus. The
`coding` Medium defines the portable shape of "ask an agent to do work";
the Claude Agent SDK is the first Focus, shipped as an extra so it's
optional. `vekna run "<prompt>"` returns as sugar for a one-rite ritual
using this Medium.

**What ships.**
- `vekna.folio.coding` — `coding` Medium with portable params (`prompt`,
  `model`, `system`, `cwd`); `CodingFocusProtocol`; `CodingResult`
  with `.text`, `.tool_calls`, `.session_id`, `.ok`. No SDK import.
- `vekna.folio.coding_claude` — `ClaudeCodingFocus` implementing the
  protocol via `claude-agent-sdk`. Pulled in by `pip install vekna[coding-claude]`.
- Approval round-trip: the SDK's `can_use_tool` callback emits
  `ApprovalRequested` over the wire; the overseer routes to the active
  surface; the answer comes back; the future resolves. Same pattern in
  standalone (stdin prompt).
- `--auto-approve <tool>` flag and per-Focus options
  (`focus_options=ClaudeOptions(...)`) for Claude-specific knobs
  (skill files, agent presets, etc.) without polluting the Medium.
- `vekna run "<prompt>"` — sugar that constructs a one-rite ritual using
  the `coding` Medium with default Claude Focus, attaches if an
  overseer is up, falls back to standalone otherwise.
- `vekna rituals list` / `vekna rituals run <name> [--flag …]` —
  discovers a project's `rituals.py`, lists registered rituals with their
  signatures, runs them; ritual function parameters → Click flags via
  `inspect.signature`.

**Scope.**
- `vekna.folio.coding/{pacts,mediums,register}.py`.
- `vekna.folio.coding_claude/{links/claude_sdk,focus,register}.py`
  — `links/claude_sdk.py` is the only place that imports
  `claude-agent-sdk`.
- Lexicon's compendium gains explicit `try/except ModuleNotFoundError`
  loading for `coding_claude` so missing extras surface only when a
  ritual actually reaches for the Medium.
- Overseer-side wiring for `ApprovalRequested` round-trips.
- `gates/cli/click/rituals.py` — adds `vekna run`, `vekna rituals list`,
  `vekna rituals run`. Discovers `./rituals.py` via importlib.
- Example: a real `fix_and_commit` ritual using `coding` + `shell` +
  `repeat` + `decide`.

**Out of scope.** TUI (Feature 4). Multi-Focus-per-Medium. Persistence
(Feature 6).

**Acceptance.**
- `pip install vekna[coding-claude]`, then `vekna run "write a haiku"`
  prints streamed output and exits 0. Without the extra, the same command
  exits with a clear "missing Focus" message.
- The motivating pattern works end-to-end:

  ```python
  @ritual
  async def fix_and_commit() -> None:
      async for _ in repeat(name="fix-until-green", bound=5):
          await coding(name="fix", prompt="fix the failing tests")
          r = await shell(name="test", cmd="mise run test")
          if await decide(name="green?", outcome=r.ok):
              break
      await coding(name="commit", prompt="commit the changes")
  ```

  Run from terminal A while terminal B has `vekna` running: the Grimoire
  renders live in B, approvals route through B, ritual completes.
- `vekna rituals list` shows registered rituals and their typed flags.
- Import errors in `rituals.py` are reported clearly, not swallowed.

---

> **Note:** Features 4–9 below still carry the older orchestrator framing in
> places. The overseer model from Feature 2 onward is the canonical one;
> these features inherit it (Vekna runs the dashboard, the ritual subprocess
> runs the work, surfaces are wire-protocol consumers). Each will be
> reshaped to match `PLAN_GRIMOIRE.md` when it's planned.

## Feature 4 — Textual TUI as the default surface

**Version:** `0.5.0`

**Goal.** Promote the overseer's CLI Grimoire view to a Textual dashboard:
running rituals across all projects in a sidebar, drill-in to any one
ritual's live tree, approval/decide/ask modals, peer-attach friendly. Same
wire protocol, richer surface.

**What ships.**
- `vekna rituals run <name>` launches a Textual app by default.
- `vekna` (no subcommand) walks up from `cwd` to the nearest directory
  containing `rituals.py` or `.vekna.toml`. If a peer process is
  already running a ritual for that project root, attaches a TUI to
  it; otherwise starts the TUI with a workflow picker.
- `--no-tui` keeps the terminal streaming behaviour from feature 3.
- Layout: left column = workflow tree (pending / running / done);
  right column = active step's live output; bottom bar = status.
- Approval modals pop up for `can_use_tool`, `approve`, `ask`, `pause`.
- Quit / cancel (`q` or Ctrl-C) stops the run gracefully for the host;
  peers disconnect cleanly.
- Scrollback on finished steps.
- **Peer-attach socket.** First `vekna` in a project root opens
  `/tmp/vekna-run-<sha(project_root)>.sock` and publishes bus events
  on it. Subsequent `vekna` calls in the same root become TUI-only
  peers. Host exit closes the socket and peers exit with a message.

**Scope.**
- `gates/tui/textual/app.py` — Textual `App` subscribing to the bus
  (local or remote over the peer socket).
- `gates/tui/textual/widgets/` — tree, stream panel, modal prompts.
- `pacts/bus.py` additions — minor event fields the TUI needs
  (`step_id`, `run_id`, byte/line deltas).
- `pacts/peers.py` + `links/peers/socket.py` — serialise bus events
  over a Unix socket; client/server halves for host vs peer role.
- `mills/project.py` — project-root discovery (`rituals.py` or
  `.vekna.toml` walk-up).
- `inits/rituals.py` — decide role (host vs peer vs fresh) at startup
  and wire the right surface.

**Out of scope.** Multiple concurrent streams (feature 5), persistence,
cross-machine peers.

**Acceptance.**
- Running a 3-step workflow shows live progress, approvals appear as
  modals, final state marks steps done.
- Running `vekna` in a second terminal in the same project directory
  attaches a second TUI to the same live run; approvals can be
  resolved from either window.
- Killing the host process causes peers to exit cleanly with a
  "run ended" message, not a traceback.
- `--no-tui` keeps the old path working.
- TUI quits cleanly, never leaves agent processes behind.

---

## Feature 5 — `parallel` primitive and multi-agent TUI

**Version:** `0.6.0`

**Goal.** Run multiple agents concurrently, each with its own context and
stream. The TUI shows them side-by-side.

**What ships.**
- New primitive: `parallel(*steps)` — awaits all, returns a tuple of
  results; any failure propagates once all peers finish (`asyncio.gather`
  semantics, configurable).
- Engine emits per-step events with a stable `step_id` so the TUI can
  route streams to the right panel.
- TUI splits the right pane into tabs (or a grid) when concurrent steps
  are live; approval modals are per-step and queue if multiple arrive
  simultaneously.
- Each concurrent `Agent(...)` uses its own SDK session — no shared
  context.

**Scope.**
- `mills/primitives.py` — add `parallel`.
- `pacts/rituals.py` — `StepId` type, `ParallelGroup` event.
- TUI widget work — tab bar / grid and modal queue.
- Concurrency tests against the engine (pure `mills/`, no SDK).

**Out of scope.** Dependency graphs between parallel branches (users
compose their own `gather`).

**Acceptance.**
- A workflow running two agents in parallel shows two live streams and
  completes.
- Approval modals from both streams queue correctly; user decisions go
  to the right future.

---

## Feature 6 — Persistence and `vekna rituals resume`

**Version:** `0.7.0`

**Goal.** A run survives a restart. Every run is a directory under
`~/.config/vekna/runs/<run_id>/` with SDK session IDs, step log, and the
args used to invoke the workflow.

**What ships.**
- Every run creates `~/.config/vekna/runs/<run_id>/run.json` and appends a
  JSONL event log.
- `Agent(...)` records SDK session IDs so a resumed run can rejoin the
  same conversation.
- `vekna rituals resume <run_id>` picks up where the previous process
  left off — replays completed step state, re-enters the current step.
- `vekna rituals list --runs` shows recent runs with status.
- A failed run stays in the directory until `vekna rituals prune` is
  called.

**Scope.**
- `pacts/runs.py` — `Run`, `StepRecord` DTOs.
- `specs/rituals.py` — `RUN_DIR` constant.
- `links/runs/filesystem.py` — JSON + JSONL writer/reader.
- `mills/rituals.py` — engine emits writer events; a resume path that
  replays state up to the first in-progress step.
- `gates/cli/click/rituals.py` — `resume`, `prune`, `list --runs`.

**Out of scope.** Moving runs between machines; remote storage.

**Acceptance.**
- Interrupt a running workflow mid-step, run `vekna rituals resume` — it
  picks up at that step.
- Completed steps aren't re-run.
- Agent steps reuse the prior SDK session (validate by asking a
  context-dependent question across resume).

---

## Feature 7 — Web view (read-only, then interactive)

**Version:** `0.8.0`

**Goal.** Same events, different surface. A local web page that shows the
active run, streams agent output, and (later in this release) fields
approvals.

**What ships.**
- `vekna web` serves a single-page app on `127.0.0.1:PORT` subscribing
  to the bus over WebSocket.
- Read-only first: workflow tree, step streams, approval requests
  visible but not actionable.
- Second cut in the same release: approval buttons wired to the same
  `resolve()` mechanism as the CLI/TUI.
- Auth: localhost-only, short-lived token in the URL for `0.0.0.0` use
  (off by default).

**Scope.**
- `gates/web/fastapi/app.py` (or `aiohttp` — pick one during planning).
- Static SPA bundle (keep minimal — prefer HTMX/Alpine over a build
  toolchain, or inline a tiny React if genuinely needed).
- `links/web/broadcast.py` — WebSocket fan-out.
- No engine changes — it's another bus consumer.

**Out of scope.** Multi-user, remote access, history browsing UI (the
data is on disk from feature 6; add a history page in a later release if
users ask).

**Acceptance.**
- Start a workflow, open the web view, see the same state the TUI shows.
- Approve from the browser; the engine unblocks.
- Closing the tab doesn't kill the run.

---

## Feature 8 — WhatsApp notifications and approvals

**Version:** `0.9.0`

**Goal.** Get pinged — and approve — when away from the machine.

**What ships.**
- Push a WhatsApp message for every `ApprovalRequested` event when
  enabled via config.
- Reply `yes` / `no` / `skip` in WhatsApp → `resolve()` routes the
  decision.
- Config via `~/.config/vekna/config.toml`: provider (Twilio /
  WhatsApp Cloud API — pick in planning), number, token from env.
- Opt-in per workflow: `@workflow(notify=["whatsapp"])` or global
  default.

**Scope.**
- `pacts/notifications.py`, `mills/notifications.py` — generic
  notification hook.
- `links/whatsapp/<provider>.py` — concrete adapter.
- `gates/webhook/<provider>.py` — receives inbound replies, routes to
  the approval bridge.
- Security review for webhook signature verification before merge.

**Out of scope.** SMS, Slack, Discord (same pattern, trivial to add
later as separate features).

**Acceptance.**
- Trigger a workflow, step away, receive a WhatsApp message, reply
  `yes`, workflow proceeds.
- Replies for stale runs (>5 min or after process exit) are ignored
  with a helpful message.

---

## Feature 9 — 1.0 hardening

**Version:** `1.0.0`

**Goal.** The product is usable; now make it robust and documented.

**What ships.**
- `README.md` rewritten around rituals; tmux gets a section.
- Example `rituals.py` library (at least: PR triage, test-and-fix loop,
  migration babysitter).
- Error pathways audited — SDK disconnects, resume on corrupt run dir,
  malformed `rituals.py`.
- Telemetry hooks (opt-in) for measuring primitive latency.
- Removal of any transitional shims left from feature 0 (if any).
- Deptry, pip-audit, mypy strict, vulture all clean.

**Out of scope.** Everything that doesn't move the product from
"it works for me" to "it works for a second user."

**Acceptance.**
- A stranger can follow the README, write a three-step workflow, run
  it end-to-end from either TUI or web.
- `mise run check`, `mise run test`, `mise run diff-cover` pass on main.

---

## Resolved decisions

1. **Vekna is an overseer, not an orchestrator.** Rituals run in their own
   subprocess in the project's environment; Vekna observes via a Unix
   socket and multiplexes surfaces. Rituals work fine without Vekna —
   standalone mode renders to stdout and prompts on stdin.
2. **Provider-agnostic core.** Claude Agent SDK is one Focus of one
   Medium (`coding`), shipped as `vekna[coding-claude]`. The lexicon and
   the `coding` Medium have no SDK import.
3. **Three-layer package layout** — `vekna.{pacts,specs,mills,links,gates,inits}`
   (overseer), `vekna.lexicon` (SDK), `vekna.folio.*` (split-ready
   bundles). Import-linter forbids core ↔ lexicon/folio imports and
   folio ↔ folio imports.
4. **Transport is a Unix domain socket** at `/tmp/vekna-<uid>.sock` (one
   per user, cross-project, configurable). Newline-framed JSON Pydantic
   DTOs. Rituals are the canonical client; replay the full Grimoire on
   every (re)attach. TCP / network access is deferred.
5. **Derived Grimoire.** The agenda is the live tree of rite invocations.
   Flow mediums (`decide`, `repeat`, `branch`, `attempt`, `parallel`) in
   `folio/flow` mark significant control-flow points. Raw `if`/`while`
   stays legal but invisible to the Grimoire.
6. **One active Focus per Medium for v1.** Multi-Focus-per-Medium
   parallelism (Claude + OpenAI side-by-side in one ritual) is deferred.
7. **`claude-agent-sdk` — track the latest, behind an extra.** Pin loosely
   (`>=X.Y,<X+1`) on the `coding-claude` extra. The base wheel does not
   pull it.
8. **Tooling — mise everywhere.** Dependencies via poetry, commands via
   `mise run …`. Nothing changes on that front.
9. **Python floor stays at 3.10.** Vekna is added as a dev dep to other
   projects; the floor must be permissive. Bump only on security fixes or
   upstream EOL.

### Dependency policy

All runtime deps pinned with lower bounds only (`>=X.Y`), capped only at
the next major (`<X+1`) to avoid surprise breakage. Raise floors only
when a security advisory or upstream EOL forces it. This keeps vekna
installable alongside arbitrary project dep sets.

### Peer-attach model (superseded — see `PLAN_GRIMOIRE.md`)

The original peer-attach plan made the engine live inside the first
`vekna` process per project root. The overseer model replaces this:

- Vekna is the daemon. Rituals are subprocesses that connect to it.
- One Unix socket per user (`/tmp/vekna-<uid>.sock`) — cross-project, not
  per project root.
- A second `vekna` invocation attaches as a peer surface to the existing
  daemon and shares its view.
- A ritual surviving the overseer's death is fine: it falls back to
  standalone (stdout/stdin) and re-attaches when the overseer returns.

---

## Not planned (deliberately)

- Cloud-hosted runs, SaaS control plane.
- **Multi-Focus-per-Medium in one ritual** (e.g. Claude and OpenAI
  side-by-side as two `coding` Foci in the same ritual). The
  architecture supports a swap of the active Focus, just not the
  parallelism. Reachable later if users ask.
- **Network-exposed overseers** (TCP binding, auth tokens, TLS). v1 binds
  a Unix socket on the local host.
- A graphical workflow editor. Rituals are Python — that's the point.
- Merging tmux mode with rituals mode. They coexist as two CLI
  subgroups; users pick one per project.
