# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog],
and this project adheres to [Semantic Versioning].

## [Unreleased] - ???

## [0.3.0] - 2026-07-27

### Added

- **`coding` medium** (`vekna.folio.coding`) — hand work to an agent from
  inside a step. Configuration bundles into
  `CodingOpts(model=..., system=..., cwd=..., gate_tools=..., focus_options=...)`
  — configuration meaning one is safe to reuse across calls, which is the point
  of bundling it. Every field but `focus_options` is portable too, saying the
  same thing whichever Focus answers; that one is read by the Focus it was
  built for and ignored by any other. `output=SomeModel` validates the agent's
  reply and returns it typed, raising `CodingOutputError` when it does not fit.
  Permissive by default: tool use is gated only when a call passes
  `gate_tools=[...]`, which turns each matching tool into a `decide`
  round-trip.
- **Session continuity is the author's** — `coding(prompt, session=..., key=...)`
  declares which thread of agent memory a call is on. `session` says whether the
  call resumes: `Session.NEW` is a fresh context and the default, since a step
  is a task boundary and carrying context across one by default contradicts what
  the boundary is for; `Session.CONTINUE` carries on. `key` says which thread —
  `merge_ready`'s repair loop keys its own, so a second attempt knows what the
  first already tried, while an unkeyed `continue` follows whichever agent call
  ran last. `new` with a key starts that thread over. Both are parameters rather
  than knobs on `CodingOpts`, because a thread is per-call identity and not
  reusable configuration; a word that is not one of the two, or a key naming
  nothing, raises `CodingSessionError`. The medium resolves the declaration
  against a per-cast session book and hands the Focus a plain session id; the
  rite's telemetry records both halves of the declaration as well as the id, and
  a declared thread the Focus gave no id for says so on the rite rather than
  going unrecorded in silence.
- **Claude Agent SDK focus** (`vekna.folio.coding_claude`) — the first Focus.
  `_links.py` is the only module importing `claude-agent-sdk`.
- **`ask_human`** — the agent can put a question to the operator mid-rite,
  free-text or multiple-choice, answered on whichever surface is attached.
  Offered on every `coding` call, including calls with a custom `system=`.
- **Focus registry in the lexicon** — `register_focus` / `resolve_focus`, so a
  folio never imports another folio. A missing or broken Focus surfaces as
  `FocusMissingError` with an install hint when a ritual reaches for the
  medium, not at import time.
- **`vekna cast --prompt "<text>"` / `-p`** — a one-step cast on the `coding`
  medium with no `rituals.py` required. It runs through the normal engine, so
  grimoire, renderer and budgets all apply.
- **`vekna rituals list` / `vekna rituals show <ritual>`** — `list` prints each
  ritual with the flags its components take; `show` adds `max_steps`, the
  component flags, and a step graph read off each function's source. The graph
  is best-effort: a `goto` whose target is computed rather than named does not
  appear.
- **Live grimoire rendering** — `Grimoire(on_event=...)` fires on every append,
  replacing the post-hoc replay loop. Agent text and shell output both stream
  into the rite as `RiteDelta`; per-call telemetry rides `RiteFinished.result`.
- **`rituals.py` at the repo root** — vekna's own rituals, cast on itself:
  - `cover_diff`, a diff-coverage loop that measures with `shell`, hands the
    uncovered lines to `coding`, and repeats under an attempt budget.
  - `review`, which reads this branch's diff and returns findings under a
    schema, with a read-only agent.
  - `merge_ready`, which runs `prcheck` and `test` **concurrently** and hands
    whatever went red to an agent, under a budget and a `decide` per attempt.
  - `triage`, which reads a GitHub issue or PR through `gh`, has an agent size
    it against the codebase, and routes on your answer.

  The file is now linted by `black`, `ruff`, `codespell` and `pylint`, and
  `tests/integration/cli/test_project_rituals.py` drives it through
  `rituals list` / `rituals show` so a broken ritual fails the suite rather
  than the next cast.
- **Concurrency inside a step** — a step may hold several medium calls at once
  (`asyncio.TaskGroup` over two `shell` calls). Each opens its own rite, since a
  Task copies the contextvar the runtime hangs rites from; the engine needed no
  change and steps themselves stay sequential.

### Changed

- **A transition carries a pydantic model or nothing.** `goto(target, payload)`
  and `done(result)` raise `RitualBoundaryError` for anything else, checked
  where the transition is built — mypy reads `src/`, and a transition is
  written in the author's `rituals.py`, which it never sees. A `@step` may
  still admit several shapes (`Lint | Coverage`) as long as every member is a
  model; a ritual's components stay a single model, being one CLI interface.
- **A cast's result prints as JSON.** `result: {"covered":true,"remaining":3}`
  rather than a pydantic repr, and `result: null` when a ritual finishes with
  nothing.
- **A malformed `.vekna.toml` stops the command.** It used to be swallowed:
  every validation failure read as "no modules, no files", so a typo loaded
  nothing and left the next cast to fail with `no ritual named ...`, naming
  neither the file nor the mistake. It now exits 2 with the path and pydantic's
  complaint. `[rituals]` rejects unknown keys for the same reason; the
  top-level table still accepts others.
- **`@ritual` takes a declared components model.** The entrypoint's parameters
  used to be reflected into a Pydantic model by `create_model`, a type the
  author never saw. It now takes exactly one parameter, a model written in the
  ritual's own source — the same rule `@step` has always had for its payload:

  ```python
  class FixTests(BaseModel):
      bound: int = 3


  @ritual("fix_tests")
  async def fix_tests(components: FixTests) -> Transition:
      return goto(fix, Attempt(left=components.bound))
  ```

  Flags, `rituals list` and `rituals show` are unchanged — they read the
  model's fields either way — but defaults, validators and
  `Field(description=...)` are the author's to write now. A ritual needing
  nothing takes the new `NoComponents`. Zero parameters, two parameters, or an
  annotation that is not a `BaseModel` subclass raise `RitualDefinitionError`
  when the ritual is defined; components that do not match the declared model
  raise the new `RitualBoundaryError` at the cast's entry boundary, the
  counterpart to the step boundary's check.
- **The GLIMPSE layering inside a package is enforced, not just documented.**
  The six `forbidden` contracts only ever governed the top-level packages, so
  the layer table in `docs/architecture.md` was a convention nothing checked —
  and two modules had inverted against it: `folio/shell/_mills` imported
  `_links`, and `wire/_links` imported `_mills`. There are now 31 contracts,
  one per layer per package, and every module sits in a layer.
- **`gates` may import only `pacts`.** Stricter than textbook GLIMPSE: every
  layer knows the contracts and `inits` binds them, rather than a gate reaching
  for a service. `links` and `mills` are peers — neither imports the other.
- **The root project may not import the lexicon.** `vekna` (daemon) and `vekna
  cast` are one binary, so importing the CLI must never pull ritual code,
  folios or the agent SDK into the daemon process. `inits/cli.py` reaches the
  cast runtime by name at call time, typed through a `Protocol` and `cast()` —
  no mypy override, unlike the `getattr`-based indirection this restores.
- **`vekna.lexicon.entry` is gone.** Six of its nine exports had no consumer
  anywhere; the other three were CLI entry points a `rituals.py` can never use.
  Deleting it made the whole cast runtime — `run_cast`, `Grimoire`,
  `Compendium`, `StandaloneRenderer` — private. `lexicon/_gates.py` became
  `_inits.py`: its entry points need `_mills` and `_links`, and `inits` is the
  only layer permitted to bind them.
- **The grimoire no longer speaks the wire protocol.** It has its own
  vocabulary — `RiteBegan` / `RiteStreamed` / `RiteEnded` in `lexicon/_pacts`,
  carrying no `cast_id` — so `vekna.wire` can version independently of the
  engine, which is the property the spec always claimed for it. `vekna.wire` is
  consequently dormant until 0.6.0 adds the projection at the socket edge.
- **Every lexicon module now sits in a layer.** `_dispatch`, `_graph`, `_loader`
  and `components` were exempt from every contract because their names matched
  no layer — which is how `_gates` reached `_mills` unnoticed. `_mills` and
  `_links` became packages so the two typing exemptions stay scoped to
  `_mills/dispatch.py` and `_links/loader.py` instead of covering the engine.
- **Component types moved to `vekna.lexicon`.** `from vekna.lexicon import File`
  replaces `from vekna.lexicon.components import File`; the `components` module
  is gone. One door for the ritual author instead of two.
- **`folio/shell` and `wire` lost their `_mills`.** `shell()` moved in beside
  `run_bash` — three lines, no branches, no business logic. `wire`'s frame codec
  moved into `_pacts`, beside the DTOs it serialises.
- **`reset_foci` and `Channel.emit` left the public API.** The first was used
  only by tests; the second had been dead since it was written. Removing `emit`
  left `WireMessage` unused in `lexicon/_pacts`, which began the wire unpicking
  above.
- **Each folio registers through an `_inits.py`.** `register()` was living in
  `_mills` (`coding`) and `_links` (`coding_claude`); registering handlers is
  what the inits layer is for. `_load_folios` calls `register()` on the package,
  so nothing outside changed.
- **`approve` and `ask` are now one adaptive `decide`.** `decide(prompt)`
  returns `bool`; `decide(prompt, options=[...])` and `decide(prompt,
  free=True)` return `str`. One wire pair (`DecideRequested` /
  `DecideResolved`) replaces the `Approval*` and `Ask*` messages.
- `claude-agent-sdk` is a plain runtime dependency. The planned
  `coding-claude` extra was dropped, so the base wheel pulls it.
- `docs/reborn/03-coding-folios.md` and `00-common.md` now describe what
  shipped rather than what was designed.
- **`WorkflowBudgetExceededError` → `StepBudgetExceededError`.** "Workflow" was
  not this project's vocabulary.
- **`vekna.lexicon` split into two doors.** It keeps the ritual author's API;
  CLI and cast-runtime plumbing (`main`, `rituals_list`, `rituals_show`,
  `run_cast`, `Grimoire`, `Compendium`, `StandaloneRenderer`, `probe_daemon`)
  moved to `vekna.lexicon.entry`. A `rituals.py` imports only the former.
- **`FocusReply` carries typed telemetry** (`session_id`, `num_turns`,
  `cost_usd`) instead of a `dict`, and is `extra="forbid"` — a focus that
  misspells a field now fails at the boundary rather than silently losing it.
  `FocusReply.structured` is gone; the reply text is validated directly.
- **Focus registration is explicit.** The cast runtime calls each folio's
  `register()`; importing `vekna.folio.coding_claude` no longer registers as a
  side effect. `resolve_focus` lost its `hint` parameter — a medium declares
  what it needs once, via `expect_focus`.
- **`emit_delta`** replaces the identical delta-sink closures the `shell` and
  `coding` folios each carried; `current_rite_id` leaves the public API.
- `rituals_main(argv)` became `rituals_list()` / `rituals_show(name)`.
- `lexicon/_dispatch` split into `_dispatch` (reflection), `_graph` (the AST
  step-graph reader, now under strict mypy) and `_loader` (file/module/TOML
  loading). `wire/_pacts` likewise sheds framing to `wire/_mills` and
  `wire/_links`.

### Deprecated

### Removed

- **The tmux subsystem.** `vekna tmux`, `vekna tmux notify`, `daemon` and
  `status-bar`, along with `gates/`, `links/`, `mills/`, `pacts/`, `specs/`,
  `edges/` and the `libtmux` dependency. Claude Code ships its own
  notifications and nothing else consumed it; 0.6.0's daemon is built fresh
  against `vekna.wire`. 14 import-linter contracts collapse to 6.
- `examples/` — its contents moved to `rituals.py` at the repo root, and the
  integration tests that copied from it carry their own fixtures now.

### Fixed

- **An optional component crashed `rituals list`, `rituals show` and `cast
  --help` on Python 3.11–3.13.** Flag rendering read `field.annotation.__name__`,
  and a union has none before 3.14 — `str | None` raised `AttributeError` there
  and printed `<Union>` on 3.14. A second spelling hid behind the same line: 3.14
  merged `typing.Union` into `types.UnionType`, so `File | None` is a `UnionType`
  on 3.14 but a *typing* union on 3.11, where an isinstance check misses it and
  the flag read `<Optional>`. Both are handled, `Annotated` is unwrapped, and an
  optional `--only` now prints the type it takes: `<Path>`. CI ran the whole
  3.11–3.14 matrix green throughout, because no ritual had such a component yet.
- **Two concurrent rites' output was indistinguishable.** The standalone
  renderer indents a delta by its rite's depth alone, so two mediums running at
  once interleaved with nothing to say which said what. On an append-only stream
  a rite with a live sibling now holds its output and emits it in one block
  before its own `✓`; a rite running alone still streams live, unchanged. A
  surface that can re-render wants the opposite, which is the sink's decision to
  make when the TUI and IM sinks arrive.
- **`cover_diff`'s prompt could crash on the report it was formatting.** It went
  through `str.format`, and the substituted value is pytest's own output — where
  an assertion diff over a dict carries braces that `format()` raises on. The
  report is concatenated now, and reads last.
- **A `.vekna.toml` naming the `rituals.py` beside it broke every command.**
  `files` is additive on top of the file found by walking up, and nothing
  deduped, so being explicit about your own rituals file made `cast`, `rituals
  list`, `rituals show` and `--help` all fail with `ritual '<name>' is already
  registered` — naming neither source. Ritual files are now skipped if already
  loaded (keyed on the resolved path, so `..` and symlinks collapse), and
  modules are deduped by name, which fixes the same break when a global and a
  project config list one module. Two genuinely different files claiming one
  ritual name is still an error, and now says which two.
- **A shell line over 1 MiB crashed the cast with a traceback.** `StreamReader`
  iterates by lines and `readline` raises past its limit — clearing its buffer,
  so the output was lost too. `_drive` catches only `RitualError`, so it escaped
  as an unhandled traceback on output as ordinary as a minified bundle or
  one-line JSON. `run_bash` reads chunks and splits lines itself; `read()` has
  no limit, so the failure mode is gone rather than reported. Multi-byte UTF-8
  split across a chunk boundary survives via an incremental decoder.
- `run_bash` never drained stdout: the first `asyncio.gather` argument had lost
  its `_pump(` wrapper, passing a raw tuple where a coroutine belonged.
- **A failing rite was never journaled as failed.** `run_cast` called
  `rite_finished` after its `try/finally`, so a step that raised left an open
  rite; `medium_rite` always finished with `status="ok"`, so a medium that
  raised was recorded as a success. `RiteFinished.status` could therefore never
  be `"error"` in production and the renderer's `✗` was unreachable. Both call
  sites now share one context manager.
- **Config-relative ritual files resolved against the cwd.** A repo-root
  `.vekna.toml` broke as soon as you worked from a subdirectory, and a global
  `config.toml` entry meant a different file in every directory. Paths resolve
  against the config file now.
- **`--a --b` read `--b` as the value of `--a`** and never set `b`. A value
  starting with `--` is rejected; `--a=--b` passes one deliberately.
- **`cast_id` was the ritual name**, so two concurrent casts of one ritual
  shared the wire's correlation key for deltas, decisions and locks.
- A `@medium`-decorated function reported `__name__ == "wrapped"`.

### Security


## [0.2.0] - 2026-06-28

### Added

- **`vekna cast` command** — runs a ritual defined in a local `rituals.py`.
  The runner loads the module in-process via `importlib`, dispatches to the
  named `@ritual` entrypoint, and prints a structured Grimoire to stdout.
  `vekna cast --help` lists available rituals.
- **`vekna.lexicon` SDK** — the public surface for authoring rituals:
  - `@ritual` marks a CLI entrypoint (the opening transition); `@step` marks a
    task that takes a typed Pydantic payload and returns a `Transition`.
  - `goto(step, payload)` / `done(result)` route the trampoline by returned
    value, targeting steps by direct function reference. Input and output
    payloads are validated at every step boundary.
  - **Bounded execution** — `@ritual(max_steps=N)` caps total hops and
    `@step(max_visits=N)` caps per-step visits; exceeding either raises
    `WorkflowBudgetExceededError`.
  - `Grimoire`, `Compendium`, `RiteContext`, and `current_rite` expose the run
    record and execution context.
- **`@medium` machinery** — rituals interact with the outside world through
  mediums (`RiteContext`, `Channel`), keeping I/O out of step logic.
- **`vekna.folio.flow`** — `decide`, `approve`, and `ask` helpers prompt the
  user and route the answer back into the workflow.
- **`vekna.folio.shell`** — a shell medium (`shell`, `ShellResult`) for running
  bash commands, with focus handling.
- **`vekna.wire`** — typed DTOs and length-prefixed framing for the daemon
  protocol.
- **Standalone renderer** — when no daemon socket is present, ritual prompts and
  output render directly to the terminal; probing the absent socket is silent
  and non-blocking (`probe_daemon`, `StandaloneRenderer`).
- **`.vekna.toml` configuration** read via `tomli` (on Python < 3.11).
- **`fix_demo` example ritual** plus end-to-end acceptance tests.

### Changed

- Top-level CLI now exposes the `cast` command alongside the existing `tmux`
  group.


## [0.1.0] - 2026-06-01

### Changed

- **CLI re-rooted under `vekna tmux`.** Existing behaviour moved one level
  deeper to free the top-level `vekna` command for the upcoming rituals
  overseer. Bare `vekna` now prints help listing available command groups.
  - `vekna` (attach) → `vekna tmux`
  - `vekna daemon` → `vekna tmux daemon`
  - `vekna notify …` → `vekna tmux notify …`
  - `vekna status-bar` → `vekna tmux status-bar`
- Bundled `tmux.conf` updated to call `vekna tmux status-bar` in its
  `status-right` line.
- Claude Code notification hook is now
  `vekna tmux notify --app claude --hook Notification`.


## [0.0.4] - 2026-04-21

### Added

- **Single global daemon** — one `vekna` process now handles all sessions. The
  Unix socket lives at `/tmp/vekna-<uid>.sock` (one per OS user) instead of
  one socket per project directory.
- **`vekna daemon`** command starts the server in the foreground; useful for
  debugging or running it under a process supervisor.
- **`vekna status-bar`** command prints the pending-notification text for a
  session, intended to be called from the tmux `status-right` line so the
  count is always visible without switching panes.
- **Bundled `tmux.conf`** shipped with the package; sourced automatically when
  `vekna` creates a new session. Provides Alt-key window bindings and wires up
  the `vekna status-bar` status-right segment.
- **Session registry** in the server tracks active sessions and their pending
  notification counts.
- **`EnsureSession` hook** — the server creates a named tmux session on demand
  (with the correct `start_directory`) when `vekna` is invoked in a project.
- **`StatusBar` hook** — the server returns formatted status-bar text per
  session, including a deterministic emoji + colour badge derived from the
  session name (SHA-256 hash mod palette) so multiple sessions are visually
  distinct at a glance.
- **`on_session_visited` callback** in `SelectPaneHandler` — called when the
  user lands on a session, either by direct pane-switch or by clearing a marked
  window; triggers `ServerMill.clear_pending` to reset the notification count.
- **`session_name_for_pane()`** on `TmuxLink` — looks up which tmux session a
  given pane belongs to.
- **`App` and `Hook` str-enums** in `pacts/bus` replace raw strings throughout,
  so typos are caught at type-check time.
- **`drain()`** on `EventBus` and `EventBusProtocol` — waits for in-flight
  handlers to finish before the socket server stops.
- **`DisplayErrorHandler`** handles `Error` events by calling
  `display_message` on the tmux link, surfacing invalid-payload errors to the
  user directly in the terminal.
- **`mise run coverage`** command added for line-coverage reporting.
- `vekna notify` now accepts `--app` and `--hook` flags and reads the
  hook payload from stdin, making it suitable as a drop-in Claude Code
  hook: `echo "$CLAUDE_HOOK_DATA" | vekna notify --app claude --hook Notification`.
- Notifications carry the full hook payload to the server, so future
  handlers can act on message content.

### Changed

- `vekna` (no arguments) now ensures the daemon is running (spawning it if
  needed, waiting up to 3 s for the socket to appear), sends an `EnsureSession`
  request, then attaches to the created tmux session.
- The server runs in **daemon mode**: `run()` loops indefinitely via an
  `asyncio.Event` instead of blocking on `tmux attach`, so a single process
  can serve many concurrent sessions.
- `TmuxLink.ensure_session` now accepts `start_directory` and sources the
  bundled `tmux.conf` on creation.
- Session-aware handlers: `SelectPaneHandler` and `DisplayErrorHandler` derive
  the session name from `session_name_for_pane` instead of assuming a single
  session; `_marked_windows` is now a `dict[window_id → session_name]`.
- `MarkWindowHandler` merged into `SelectPaneHandler` — pane-switching (idle)
  and window-marking (active) are handled by the same class.
- `ClaudeNotificationHandler` publishes an `Error` event on invalid payloads
  instead of raising, and forwards `event.meta` so `DisplayErrorHandler` can
  locate the correct session.
- Activity tracking switched from `session_activity` to `client_activity`,
  which tracks keyboard input rather than pane writes.
- Status bar always shows a `vekna 💀` prefix even when no sessions are
  pending, so the segment remains visible.
- Session names in the status bar and notification counts now display the
  folder name only (e.g. `myproject`), stripping the `vekna-` prefix and hash
  suffix added internally.
- `NotifyClientMill.request()` added for synchronous request/response over the
  Unix socket; `Response` model added to `pacts/socket` as the canonical
  envelope.
- Focus switching now triggers only when the session has been idle for
  at least 3 seconds (down from 5); the threshold is tunable via
  `IDLE_THRESHOLD_SECONDS`.
- When the user is active, the originating window turns red immediately
  rather than waiting for the next poll cycle.

### Removed

- `stem_from_tmux_env()` and `paths_for()` removed from `specs/constants` —
  the single daemon socket path makes per-project path derivation unnecessary.
- `seconds_since_last_keystroke` removed from `TmuxLink` (unused after the
  `client_activity` switch).

### Fixed

- Background task cancellation on Python 3.13+ no longer raises
  `CancelledError` during shutdown.


## [0.0.3] - 2026-04-13

### Added

- `vekna notify` command that signals the server to switch to the calling pane
- Asyncio unix socket server runs alongside the tmux session
- Socket client sends pane ID over `/tmp/vekna.sock`
- Window and pane switching on notification (`select-window` + `select-pane`)
- Multi-instance support: each working directory gets its own vekna
  server, tmux session, and Unix socket, keyed on a stem derived from
  the directory name plus a short hash of the absolute path. Run
  `vekna` from any project directory and it will not collide with
  other running instances.
- Typing-aware focus: if a keystroke landed in another pane within the
  last three seconds, `vekna notify` skips `select-pane` and sets the
  tmux window attention flag instead. A periodic poll clears the flag
  once the user reaches the pane on their own.
  
### Changed

- CLI entry point renamed from `antistes` to `vekna`
- CLI restructured as a click group to support subcommands
- Tmux management rewritten with libtmux (replaces raw subprocess calls)
- `ServerMill.run()` is now async; tmux attach runs in a thread executor
- `vekna notify` now reads `$TMUX` as well as `$TMUX_PANE` and routes
  automatically to the server that owns the calling pane — the global
  Claude Code hook stays literally `vekna notify` with no arguments.
- The Unix socket path is no longer the hardcoded `/tmp/vekna.sock`;
  it is now `/tmp/vekna-<basename>-<hash>.sock`, one per project.
- Package renamed from `antistes` to `vekna` across the source tree,
  imports, entry point, and linter configs. Install and import as
  `vekna`; the old name is gone.
- Socket messages use pydantic models, giving client and server a typed
  contract in place of ad-hoc dicts.

### Removed

- `links/subprocess.py` — replaced by `links/tmux.py` using libtmux

## [0.0.2] - 2026-04-07

### Added

- CLI entry point (`vekna`) that starts or attaches to a named tmux session
- Layered architecture: gates (Click CLI), mills (server logic), links (tmux subprocess calls), pacts (protocols)
- Pre-commit hooks: ruff, mypy, bandit, pylint, pytest
- CI workflow with GitHub Actions
- Dependabot configuration for pip and GitHub Actions
- Integration and unit test scaffolding with pytest

## [0.0.1] - 2026-04-07

- initial release

<!-- Links -->
[keep a changelog]: https://keepachangelog.com/en/1.0.0/
[semantic versioning]: https://semver.org/spec/v2.0.0.html

<!-- Versions -->
[unreleased]: https://github.com/fancysnake/vekna/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/fancysnake/vekna/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/fancysnake/vekna/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/fancysnake/vekna/compare/v0.0.4...v0.1.0
[0.0.4]: https://github.com/fancysnake/vekna/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/fancysnake/vekna/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/fancysnake/vekna/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/fancysnake/vekna/releases/tag/v0.0.1
