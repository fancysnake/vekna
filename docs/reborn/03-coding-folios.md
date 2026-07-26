# Feature — `folio/coding` + `folio/coding_claude`

**Version:** `0.3.0`

See [00-common.md](00-common.md) for Medium/Focus/Component and Component
output direction.

## Goal

First action Medium with a real third-party Focus. The `coding` Medium defines
the portable shape of "ask an agent to do work"; the Claude Agent SDK is the
first Focus. `vekna cast --prompt "<text>"` is sugar for a one-rite cast using
this Medium.

The bargain: the agent runs permissively *inside* its step — editing files and
running commands without asking — while the decision to keep going stays at the
step boundary, where a shell gate passes or an attempt budget runs out.
Non-deterministic inside a step, deterministic between them.

## What ships

- `vekna.folio.coding` — the `coding` Medium. No SDK import.

  ```python
  await coding(
      prompt,
      output=SomeModel,               # validated via TypeAdapter; failure raises
      opts=CodingOpts(model, system, cwd),
      gate_tools=["Bash"],            # opt in to a decide round-trip per tool
      focus_options=ClaudeOptions(),  # Focus-specific knobs
  )
  ```

  The portable knobs bundle into `CodingOpts` rather than spreading across the
  signature (ruff PLR0913 stays strict). Default return is `CodingResult`
  (text + telemetry); `output=T` returns `T`.
- `vekna.folio.coding_claude` — `ClaudeCodingFocus` implementing
  `CodingFocusProtocol` via `claude-agent-sdk`, a plain runtime dependency.
  `_links.py` is the only place importing the SDK, and it matches the SDK's
  message dataclasses through local `runtime_checkable` Protocols — naming them
  directly would trip `disallow_any_expr`.
- **Permissive by default.** `coding` does not gate tool use unless the call
  asks for it. `gate_tools=[...]` turns each matching tool into a `decide`
  round-trip through the SDK's `can_use_tool` callback.
- **`ask_human`** — the reverse direction, and always available: the agent can
  put a question to the operator mid-rite, free-text or multiple-choice, which
  arrives as a `decide` on whichever surface is attached. Every `coding` call
  offers it via a system-prompt append, so a custom `system=` still carries it.
- **Streamed output and telemetry.** Agent text streams into the rite as
  `RiteDelta` (`Grimoire.rite_delta`); `shell` streams its stdout and stderr the
  same way. Per-call telemetry rides `RiteFinished.result`.
- `vekna cast --prompt "<text>"` / `-p` — builds a synthetic one-step ritual
  around `coding` and runs it through the normal engine, so grimoire, renderer
  and budgets all apply. No `rituals.py` required. The positional argument is
  *always* a ritual name; an unknown name is always an error, never a prompt.
- `vekna rituals list` / `vekna rituals show <ritual>` — `list` prints each
  ritual with the flags its Components take; `show` adds `max_steps`, the
  Component flags, and a step graph.

## Scope

- `vekna.folio.coding/{_pacts,_mills}.py` — `CodingOpts`, `CodingResult`,
  `CodingOutputError` and the Medium itself.
- `vekna.folio.coding_claude/{_pacts,_links}.py` + `register()`.
- Medium↔Focus boundary types (`CodingCall`, `FocusReply`, `GateFn`, `AskFn`,
  `CodingFocusProtocol`) live in `vekna.lexicon`, so folio⊥folio stays absolute
  — `coding_claude` imports the lexicon only.
- Focus registry in the lexicon (`register_focus` / `resolve_focus`). The cast
  runtime imports `vekna.folio.coding_claude` under
  `suppress(ModuleNotFoundError)`; a broken or partial install surfaces only
  when a ritual reaches for the Medium, as `FocusMissingError` with an install
  hint, exit 2.
- `lexicon/_gates.py` — `main(argv)` for `cast`, `rituals_main(argv)` for
  `rituals`. `inits/cast.py` holds the dynamic-import shims
  (`dispatch_cast`, `dispatch_rituals`); `inits/cli.py` mounts both on Click.
- `rituals.py` at the repo root — vekna's own rituals, cast on itself.
  `examples/` is gone.

## Out of scope

TUI. Multi-Focus-per-Medium. Persistence. Locks. (`folio/process` is v0.4.0.)

## Acceptance

- `vekna cast --prompt "write a haiku"` prints streamed output, exits 0. With
  the Focus unregistered, the same command exits 2 with a clear missing-Focus
  message.
- The motivating pattern works end-to-end — `cover_diff`, as shipped in
  `rituals.py`:

  ```python
  @ritual("cover_diff")
  async def cover_diff(components: CoverDiff) -> Transition:
      return goto(measure, Uncovered(budget=components.bound))

  @step
  async def measure(state: Uncovered) -> Transition:
      result = await shell("mise run diff-cover --fail-under 100")
      if result.exit_code == 0:
          return done(CoverReport(covered=True, remaining=state.budget))
      if state.budget == 0:
          return done(CoverReport(covered=False, remaining=0))
      return goto(write_tests, Uncovered(budget=state.budget, report=result.stdout))

  @step
  async def write_tests(state: Uncovered) -> Transition:
      await coding(_FIX_UNCOVERED.format(report=state.report))
      return goto(measure, Uncovered(budget=state.budget - 1))
  ```

- `vekna rituals list` shows registered rituals and their typed flags; `show`
  adds the Component schema and the step graph.
- Import errors in `rituals.py` are reported clearly, not swallowed.
