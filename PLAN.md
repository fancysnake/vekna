# PLAN — 0.3.0 review remediation + tmux removal

Source: PR [#50](https://github.com/fancysnake/vekna/pull/50) review comment
(2026-07-25), items 1–16 of the priority report.
Shared context: [`docs/reborn/00-common.md`](docs/reborn/00-common.md)

## Outcome

Two things at once, because the second makes the first smaller. The tmux
subsystem — vekna 0.0.x–0.1.0, the whole pre-lexicon GLIMPSE core — is deleted:
Claude ships its own notifications now and nobody else uses this project. What
remains is `lexicon` + `folio` + `wire` + a thin `inits` CLI. On top of that
clean base, every P1–P3 finding from the review is fixed, so the reborn line
starts from code with no known defects and no incidental complexity carried
forward.

## Approved decisions

1. **Delete the whole pre-lexicon core** — `gates/`, `links/`, `mills/`,
   `pacts/`, `specs/`, `edges/`, `conf/tmux.conf`, the `libtmux` dependency,
   12 test files, 8 import-linter contracts. 0.6.0's daemon is built fresh
   against `vekna.wire`; `SocketServerLink` spoke a line-based
   request/response protocol, not the wire's JSONL framing, so it was never
   the reusable asset `docs/reborn/06` assumed.
2. **Two doors** — `vekna.lexicon` is the ritual author's API;
   `vekna.lexicon.entry` holds CLI entry points (`main`, `rituals_list`,
   `rituals_show`). `inits/cli.py` imports `entry` directly, so
   `inits/cast.py` and its `importlib` string dispatch are deleted along with
   the `vekna.inits.cast` mypy override — the `core-no-lexicon` contract that
   forced the indirection dies with the core. Reinstate the boundary in 0.6.0
   when a real second process needs it.
3. **Test conventions: split the difference** — integration tests move under
   `tests/integration/cli/` and `tests/integration/folio/` as the doc
   intends; `CLAUDE.md`'s "no unit tests for links" rule is narrowed so pure
   formatting/probing helpers with injected IO stay unit-testable.
4. **`WorkflowBudgetExceededError` → `StepBudgetExceededError`.**
5. **Item 5 (duplicated socket helper) closes by deletion.** The second copy
   lived in `inits/cli.py`, which Step 0 removes. `default_socket_path` /
   `_socket_alive` stay in `lexicon/_links.py` — one consumer, no move to
   `vekna.wire` until 0.6.0 gives it a second.
6. **P4 items 17–19 are not in scope**: the `probe_daemon` call stays (06
   wires it), `Channel.emit` stays (06 decides the channel's role). Step 0
   adds a comment at each site recording why.

## Config-file changes requiring explicit approval

Per `CLAUDE.md`, these need a per-case yes before the step that touches them:

- **`pyproject.toml`** — drop `libtmux`; delete 8 import-linter contracts and
  rewrite the forbidden lists of the 6 survivors; delete the
  `vekna.inits.cast` mypy override; narrow the `vekna.lexicon._dispatch`
  override to the reflection module only. (Steps 0, 9.)
- **`CLAUDE.md`** — rewrite the project description (it currently describes
  vekna as a tmux focus-switcher), the architecture layer list, and the
  Testing/Structure block. (Steps 0, 11.)
- **`mise.toml`** — `unittest` task passes `--cov=ludamus`, a leftover from
  another project, so it measures nothing. Fix to `--cov=vekna`. (Step 0.)

## Steps

### Step 0 — Delete the tmux subsystem

- Delete `src/vekna/{gates,links,mills,pacts,specs,edges}/`,
  `src/vekna/conf/tmux.conf`, `src/vekna/inits/cast.py`.
- Delete `tests/unit/test_{cli,constants,event_bus,handlers,notify_client_mill,server_mill,socket_client,socket_server,tmux_link}.py`
  and `tests/integration/test_{command,notify_flow,notify_end_to_end,daemon_end_to_end}.py`.
- `inits/cli.py` shrinks to a plain click root group mounting `cast` and
  `rituals`; bare `vekna` prints help. `ClickGate`, `ensure_daemon_running`,
  `_spawn_daemon`, `daemon_socket_path`, `_socket_is_alive` all go. It keeps
  importing `vekna.lexicon` by name until Step 10 introduces `entry`.
- `pyproject.toml`: drop `libtmux`; delete the `gates`, `links`, `inits`,
  `mills`, `pacts`, `specs`, `edges`, `core-no-lexicon` contracts; rewrite the
  forbidden lists of `wire`, `lexicon`, `folio.flow`, `folio.shell`,
  `folio.coding`, `folio.coding_claude` to name only surviving packages.
- `mise.toml`: `--cov=ludamus` → `--cov=vekna`.
- Comments at `lexicon/_gates.py` (`probe_daemon` result discarded) and
  `lexicon/_pacts.py` (`Channel.emit` unused) naming 0.6.0 as the step that
  consumes them, so neither reads as an oversight.
- Verify: `mise run check && mise run test`; `vekna --help` lists only `cast`
  and `rituals`.

### Step 1 — One rite context manager, and a failure that reaches the journal

Fixes **item 1** (P1) — the only functional defect in the review.

- `lexicon/_mills.py`: single `@asynccontextmanager async def _rite(*, name,
  category)` that starts the rite, swaps the `ContextVar`, finishes in
  `finally`, and finishes with `status="error"` when the body raises.
  `medium_rite` becomes a thin call; `run_cast`'s step loop uses the same
  manager. `root.parent_id` is already `None`, so `parent_id=parent.parent_id`
  covers both cases with no branch.
- `run_cast`'s `for _ in range(ritual.max_steps)` → `while not
  isinstance(transition, Done)` with an explicit counter, so the `Done` check
  is written once and the budget error sits next to the budget.
- New tests: a step that raises journals `RiteFinished(status="error")`; a
  medium that raises does the same; the renderer's `✗` branch is exercised for
  the first time by a real producer rather than a hand-built message.
- Verify: `mise run check && mise run test`.

### Step 2 — `_gates` input handling

Fixes **items 2, 3** (P1) and **6** (P2).

- `_build_compendium`: resolve `files = [...]` against the config file's
  parent, not `cwd` — today a repo-root `.vekna.toml` breaks as soon as you
  `cd` into a subdirectory, and a global `~/.config/vekna/config.toml` entry
  means a different file per directory.
- `_parse_flags`: reject a value starting with `--`; require the `=` form for
  those. Today `vekna cast r --a --b` silently sets `a == "--b"`.
- `Grimoire(cast_id=...)` gets a real unique id instead of the ritual name.
  `CastHello` already carries `ritual` separately, and `cast_id` is the wire
  correlation key for deltas, decisions and locks.
- Tests for each of the three.
- Verify: `mise run check && mise run test`.

### Step 3 — Typed `rituals` entry points

Fixes **item 4** (P2).

- `rituals_main(argv)` → `rituals_list() -> int` and `rituals_show(name: str)
  -> int`. Click already parses the subcommand and `@click.argument("name")`
  already guarantees arity, so `_RITUALS_USAGE`, the command whitelist, both
  arity checks and the trailing duplicate usage write are unreachable in
  production and go.
- `inits/cli.py` calls the two functions directly.
- Delete the four tests that existed only to reach the dead branches
  (`test_rituals.py` extra-argument, missing-name, unknown-command,
  no-arguments).
- Verify: `mise run check && mise run test`.

### Step 4 — `vekna.wire`: framing out of `_pacts`

Fixes **item 12-wire** (P2).

- `wire/_pacts.py` keeps DTOs only. `encode_frame`/`decode_frame` and the
  `TypeAdapter` move to `wire/_mills.py` (pure); `read_frames`, which takes an
  `asyncio.StreamReader`, moves to `wire/_links.py`. `wire/__init__.py`
  re-exports unchanged, so no caller moves.
- `tests/unit/wire/` already splits `test_framing.py` from `test_messages.py`;
  imports follow the new modules.
- Verify: `mise run check && mise run test`.

### Step 5 — A typed focus reply

Fixes **items 7, 8** (P2).

- `FocusReply` carries `session_id: str | None`, `num_turns: int | None`,
  `cost_usd: float | None` as typed fields instead of
  `telemetry: dict[str, JsonValue]`. `CodingResult` drops
  `extra="ignore"` — today a focus spelling `total_cost_usd` loses the field
  with no error anywhere, and `coding_claude/_links.py` already does that
  rename by hand.
- Drop `FocusReply.structured` and `_structured()`.
  `adapter.validate_python(json.loads(text))` and
  `adapter.validate_json(text)` are the same thing; the gated helper only
  added a silent `except ValueError: return None` and a second parse.
  `_validate_output` always validates the text.
- `record_result` still receives a JSON-shaped dict for
  `RiteFinished.result`, built explicitly from the typed fields.
- Verify: `mise run check && mise run test`.

### Step 6 — Explicit registration, and one delta sink

Fixes **items 9, 11** (P2).

- The focus registry becomes an object the lexicon owns, with a `reset()`
  seam. `_load_optional_folios` calls `module.register()` explicitly; the bare
  `register()` at the bottom of `coding_claude/_links.py` goes. Tests stop
  monkeypatching the private `vekna.lexicon._mills._foci` (two copies of one
  fixture) and stop purging `sys.modules` before and after every test.
- `resolve_focus(name)` loses its `hint` parameter; the remediation string is
  supplied at registration, so `_INSTALL_HINT` about `claude-agent-sdk` stops
  living in `folio/coding/_mills.py` — a package that knows nothing about
  which focus is missing.
- New `emit_delta(text: str) -> None` in the lexicon replaces the identical
  closures in `folio/shell/_mills.py:_streamer` and
  `folio/coding/_mills.py:on_delta`. `current_rite_id` leaves the public
  surface (it had no other caller).
- Verify: `mise run check && mise run test`.

### Step 7 — `--prompt` through the registry

Fixes **item 10** (P2).

- `folio/coding` registers a one-shot entry (`Callable[[str],
  Awaitable[str]]`, returning `.text`) alongside its focus;
  `_load_optional_folios` covers `vekna.folio.coding` too. `_prompt_ritual`
  resolves it by name.
- Deletes `_CODING_MODULE`, `_coding_medium()`, the `_HasText` Protocol and
  both `cast()`s. Returning `str` rather than the medium's result is what
  removes the structural type entirely — the lexicon may not import
  `CodingResult`, and now it does not need to describe it either.
- Verify: `mise run check && mise run test`.

### Step 8 — Vocabulary and conformance sweep

Fixes **item 12** remainder (P2).

- `WorkflowBudgetExceededError` → `StepBudgetExceededError`.
- `_validate_output(output, text)` and `_pump(stream, sink, on_line)` take
  their parameters keyword-only — the 3+ params rule this PR added to
  `CLAUDE.md`, which they were the only two new functions to break.
- `medium` gains `functools.wraps`, so decorated mediums stop reporting
  `__name__ == "wrapped"`.
- `_gates.py:108` uses `_NO_RITUALS` instead of spelling the literal again.
- Verify: `mise run check && mise run test`.

### Step 9 — Split `lexicon/_dispatch.py`

Fixes **item 15** (P3).

- `_dispatch.py` keeps reflection only: `step`, `ritual`, `_payload_type`,
  `_component_model`, `component_flags`, `source_text`.
- `_graph.py` takes the AST step-graph reader (`_transitions`, `_walk`,
  `step_graph`, `START`, `ENDS`) — pure and strictly typable.
- `_loader.py` takes file/module loading and TOML config reading, along with
  the `tomllib`/`tomli` shim currently wedged at line 34 between two unrelated
  functions.
- `medium` moves to `_mills.py`, next to `medium_rite` — it was never
  reflection.
- `pyproject.toml`: the `disallow_any_expr` / `disallow_any_explicit` /
  `warn_return_any` override now names only `vekna.lexicon._dispatch`, which
  is what the override's own comment always claimed. The graph and config
  readers become strict for the first time.
- *Alternative if you prefer fewer modules*: fold `_graph` into `_mills` and
  `_loader` into `_links`, matching GLIMPSE names exactly at the cost of two
  larger grab-bag modules. Say the word before this step and I will switch.
- Verify: `mise run check && mise run test`; the two new modules pass under
  full strict mypy.

### Step 10 — Two doors

Fixes **item 16** (P3).

| `vekna.lexicon` (ritual author) | `vekna.lexicon.entry` (CLI) |
| --- | --- |
| `ritual` `step` `medium` `goto` `done` | `main` |
| `Transition` `Goto` `Done` | `rituals_list` `rituals_show` |
| `current_rite` `record_result` `emit_delta` | `run_cast` `Compendium` `Grimoire` |
| `Channel` `RiteContext` | `StandaloneRenderer` |
| `CodingCall` `FocusReply` `CodingFocusProtocol` `GateFn` `AskFn` | `probe_daemon` `default_socket_path` |
| `register_focus` `resolve_focus` | |
| the six `*Error` types | |

- `inits/cli.py` imports `vekna.lexicon.entry` directly. `inits/cast.py` and
  its mypy override are already gone (Step 0).
- Verify: `mise run check && mise run test`; `rituals.py` at the repo root
  still imports everything it needs from `vekna.lexicon` alone.

### Step 11 — Test layout and fixtures

Fixes **items 13, 14** (P2).

- `tests/integration/cli/test_cast.py`, `test_rituals.py` — the two that drive
  the CLI entry points.
- `tests/integration/folio/test_shell.py`, `test_coding_claude.py` — folio
  integration; `test_shell.py` drives `run_cast` directly, not a command.
- `tests/integration/test_acceptance.py` stays at the root: it is the spec's
  acceptance run, not a command surface.
- `CLAUDE.md` Testing/Structure block documents all three, and the links rule
  narrows to allow unit tests for pure formatting/probing helpers with
  injected IO (`test_probe.py`, `test_renderer.py` become conformant rather
  than exceptions).
- `test_coding_claude.py`: `_RITUALS`, `_GATED_RITUALS` and `_SYSTEM_RITUALS`
  collapse into one template with the `coding(...)` call interpolated.
  `_TYPED_RITUALS` stays as written — it differs by an extra import, an extra
  model and a different `done()`, and templating it would hide real variation.
  (~40 lines, not the ~80 the review estimated.)
- Verify: `mise run check && mise run test`, same test count minus the four
  deleted in Step 3.

### Step 12 — Docs, changelog, task record

- `CLAUDE.md`: project description no longer describes a tmux focus-switcher;
  architecture layer list matches the surviving packages.
- `README.md`: tmux commands and the Claude Code hook guidance go; `cast` and
  `rituals` are the documented surface.
- `docs/architecture.md`: layer map redrawn around `lexicon` / `folio` /
  `wire` / `inits`.
- `docs/reborn/00-common.md`: drop the `vekna tmux …` line from the CLI
  surface.
- `docs/reborn/01-cli-reroot.md`: marked superseded — the subgroup it created
  no longer exists.
- `docs/reborn/06-vekna-daemon.md`: "extend the existing tmux Unix-socket
  adapter" → build the daemon socket fresh; restate "attention surfacing (the
  original soul)" in cast terms rather than tmux panes.
- `docs/reborn/10-hardening.md`, `docs/reborn/README.md`,
  `docs/features/drafts/vekna/daemon/attach-and-cast-list.md`: tmux
  references reconciled.
- `CHANGELOG.md` `[Unreleased]`: a **Removed** section for the tmux
  subsystem, plus the fixes from Steps 1–2 under **Fixed**.
- `CURRENT_TASK.md`: updated to this plan's state.
- Verify: `mise run check && mise run test`; no `tmux` match outside
  `CHANGELOG.md` history entries.

## Acceptance

- `mise run check` and `mise run test` green at every step; each step
  committed separately on `vekna-reborn`.
- A step that raises and a medium that raises both produce
  `RiteFinished(status="error")` and render `✗`.
- `vekna --help` offers `cast` and `rituals`, nothing else; `vekna cast
  --prompt "…"` and `vekna rituals list/show` behave as before.
- `grep -r tmux src/ tests/` is empty.
- Import-linter contracts pass with the reduced set; the only mypy override
  left is the reflection module.
- `rituals.py` at the repo root imports only from `vekna.lexicon`.

## Out of scope

Release/version bump. `parallel` (owed from 0.2.0). Manual smoke test against
the real Claude SDK. P4 items 17–19. Anything from 0.4.0+.
