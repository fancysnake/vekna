# PLAN — Feature 0.3.0: `folio/coding` + `folio/coding_claude`

Source spec: [`docs/reborn/03-coding-folios.md`](docs/reborn/03-coding-folios.md)
Shared context: [`docs/reborn/00-common.md`](docs/reborn/00-common.md)

## Outcome

The `coding` Medium — the last primitive Radek's daily workflows need. Agents
run permissively *inside* a step; determinism lives at step boundaries
(shell gates, `decide` sign-offs, typed payload checklists). Claude Agent SDK
is the first Focus. `vekna cast --prompt`
gives one-shot casts; `vekna rituals list/show` inspects the library.

## Approved design decisions

1. **Adaptive `decide`** (replaces `approve`/`ask` everywhere):
   `decide(prompt)` → bool (yes/no) · `decide(prompt, options=[...])` → str ·
   `decide(prompt, free=True)` → str. One wire pair: `DecideRequested`
   (prompt + optional options + free flag) / `DecideResolved` (answer).
   `prompt` stays positional (matches approved examples) — deliberate
   exception to the keyword-only rule; the rest keyword-only.
2. **`vekna cast --prompt "..."` / `-p`** — positional arg is ALWAYS a ritual
   name; unknown name is always an error. No heuristics.
3. **pyproject.toml changes pre-approved**: `claude-agent-sdk` dependency +
   import-linter contracts for `folio.coding` and `folio.coding_claude`.
   *Revised 2026-07-25*: `claude-agent-sdk` is a plain runtime dependency, not
   a `coding-claude` extra — `[project.optional-dependencies]` is dropped.
   The Focus is therefore always installed; the `FocusMissingError` path
   remains for a broken/partial install and for future Foci.
4. **Permissive by default**: `coding` does not gate tool use unless the call
   opts in (`gate_tools=[...]` → `decide` round-trip per matching tool). The
   spec's `--auto-approve` flag is dropped — auto-approve IS the default.
   (Doc updated in Step 6.)
5. **Focus registry lives in the lexicon** (`register_focus`/`resolve_focus`),
   because folio⊥folio imports are forbidden: `coding_claude` registers via
   lexicon public surface; `coding` resolves the same way. The cast runtime
   dynamically imports `vekna.folio.coding_claude` under
   `suppress(ModuleNotFoundError)`; a missing SDK surfaces only when a
   ritual reaches for the Medium (`FocusMissingError` with install hint,
   exit 2).
6. **Telemetry rides `RiteFinished.result`** (already in the wire schema);
   `Grimoire.rite_finished` gains `result=`. Streamed agent output uses the
   existing `RiteDelta` kind via new `Grimoire.rite_delta`.
7. **Ruff PLR0913 stays strict** (approved 2026-07-19): portable knobs bundle
   into `CodingOpts(model, system, cwd)` — `coding(prompt, *, output, opts,
   gate_tools, focus_options)` — and the Focus protocol takes one `CodingCall`
   plus `on_delta`/`gate` callbacks. No ruff config change.
9. **Structural matching at the SDK boundary** (approved 2026-07-25): the
   SDK's message dataclasses carry `Any`-typed fields, so naming
   `AssistantMessage`/`ResultMessage` trips `disallow_any_expr`. `_links.py`
   matches them via local `runtime_checkable` Protocols instead. No mypy
   override, no `type: ignore`.
8. **Medium↔Focus boundary types live in the lexicon** (approved 2026-07-19):
   `CodingCall` (flat: prompt/model/system/cwd/output_schema/focus_options),
   `FocusReply`, `GateFn`, `CodingFocusProtocol` move to `vekna.lexicon` so
   folio⊥folio stays absolute — `coding_claude` imports lexicon only.
   User-facing `CodingOpts`/`CodingResult`/`CodingOutputError` stay in
   `folio/coding`.

## Steps

### Step 0 — Decide consolidation
- `wire/_pacts.py`: `DecideRequested` gains `options: list[str] | None = None`,
  `free: bool = False`; `DecideResolved.choice` → `answer`. Delete
  `Approval*`/`Ask*` models; update `WireMessage` union + `wire/__init__.py`.
- `lexicon/_pacts.py`: `Channel` protocol → single
  `decide(*, prompt, options, free) -> str`.
- `lexicon/_links.py` `StandaloneRenderer`: one `decide` handling three modes
  (y/n when no options and not free; numbered choice; free text).
- `folio/flow/_mills.py`: single `decide` medium, returns `bool | str`
  (bool in confirm mode). Precise `@overload`s if mypy-strict-friendly.
- Update: `tests/unit/lexicon/test_renderer.py`, `tests/unit/folio/flow/
  test_flow.py`, wire tests, `examples/rituals.py`, integration tests.
- Verify: `mise run check && mise run test`.

### Step 1 — Live grimoire + deltas
- `Grimoire(on_event: Callable[[WireMessage], None] | None = None)` — invoked
  synchronously on every append (live rendering; replaces post-hoc replay loop
  in `lexicon/_gates.py`).
- `Grimoire.rite_delta(rite_id, delta)`; `rite_finished(..., result=None)`.
- `StandaloneRenderer` renders `RiteDelta` as indented streamed lines.
- Mediums reach their own rite id via `current_rite().parent_id` (already
  true inside `medium_rite`) — no API change.
- Verify: `mise run check && mise run test`.

### Step 2 — `folio/coding` + lexicon focus registry
- Lexicon: `register_focus(medium, focus)` / `resolve_focus(medium)` +
  `FocusMissingError`; exported in `__init__`.
- `folio/coding/_pacts.py`: `CodingResult` (text, session_id, num_turns,
  cost_usd), `FocusReply` (text, structured, telemetry),
  `CodingFocusProtocol` (async `run(*, prompt, model, system, cwd,
  output_schema, on_delta, gate)`), `CodingOutputError`.
- `folio/coding/_mills.py`: `coding(prompt, *, model, system, cwd, output,
  gate_tools, focus_options)`; resolves Focus, emits deltas + telemetry into
  the grimoire, `output=T` validated via `TypeAdapter(T)` — failure raises.
- Unit tests with a fake Focus (registry, deltas, typed output, gating,
  missing-focus error).
- Verify: `mise run check && mise run test`.

### Step 3 — `folio/coding_claude` + packaging
- Read the claude-api reference before writing SDK code.
- `_pacts.py`: `ClaudeOptions` (allowed_tools, permission_mode, max_turns —
  minimal, growable). `_links.py`: `ClaudeCodingFocus` — the only place
  importing `claude_agent_sdk`; streams text deltas, maps `can_use_tool` to
  the `gate` callback only when gating requested, collects telemetry from the
  result message, requests JSON matching `output_schema` when given.
- `__init__.py` `register()` → `lexicon.register_focus("coding", ...)`. Cast
  runtime imports it under `suppress(ModuleNotFoundError)`.
- `pyproject.toml`: `claude-agent-sdk` runtime dep + two import-linter
  contracts (pre-approved).
- Integration test with a stub `claude_agent_sdk` module in `sys.modules`.
- Verify: `mise run check && mise run test`.

### Step 4 — CLI: `--prompt` sugar
- `lexicon/_gates.py`: `--prompt`/`-p "<text>"` builds a synthetic one-step
  ritual around `coding` and runs it through the normal engine (grimoire,
  renderer, budgets all apply). Positional arg remains strictly a ritual name.
- Missing extra → clear `FocusMissingError` message, exit 2.
- Integration test (stub focus).
- Verify: `mise run check && mise run test`.

### Step 5 — `vekna rituals list` / `show`
- `inits/cast.py` gains `dispatch_rituals`; `inits/cli.py` mounts a `rituals`
  click group (`list`, `show NAME`) — same dynamic-import shim as `cast`.
- `lexicon/_gates.py` `rituals_main(argv)`: `list` reuses the help-text
  enumeration (names + typed flags); `show` prints the Component schema and a
  best-effort static step graph (`Step`/`Ritual` keep a reference to the
  original function; AST scan for `goto(<step>` targets).
- Integration tests for both commands.
- Verify: `mise run check && mise run test`.

### Step 6 — Example, docs, changelog
- `examples/rituals.py`: add `fix_list` — checklist ritual (typed
  remaining/done payload, `coding` per item, shell verify gate, `decide`
  sign-off) demonstrating the can't-forget property.
- `docs/reborn/03-coding-folios.md`: reflect delivered reality (adaptive
  `decide`, `--prompt` flag, `gate_tools` opt-in replaces `--auto-approve`,
  no `coding-claude` extra);
  `docs/reborn/00-common.md` CLI-surface line updated likewise.
- `CHANGELOG.md` Unreleased section filled (release bump only on request).
- Verify: `mise run check && mise run test`.

## Acceptance (spec, adjusted per decisions)

- `vekna cast --prompt "write a haiku"` streams output, exit 0. With the Focus
  unregistered: clear missing-Focus message, exit 2. (Integration: stubbed SDK;
  manual smoke with real SDK.)
- Checklist ritual runs end-to-end with a fake Focus; no item dropped.
- `vekna rituals list` shows rituals + typed flags; `show` adds components +
  step graph. Import errors in `rituals.py` reported clearly, not swallowed.
- `mise run check` and `mise run test` pass at every step.

## Out of scope

TUI. Multi-Focus-per-Medium. Persistence. Locks (0.5.0). `parallel` (owed
from 0.2.0, separate task). Daemon-side handlers.
