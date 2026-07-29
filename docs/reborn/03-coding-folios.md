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
      session="new",                  # which thread of memory this call is on
      opts=CodingOpts(
          model=model, system=system, cwd=cwd,
          gate_tools=["Bash"],        # opt in to a decide round-trip per tool
      ),
      focus_options=ClaudeOptions(),  # Focus-specific knobs
  )
  ```

  Every portable knob bundles into `CodingOpts` rather than spreading across the
  signature (ruff PLR0913 stays strict) — portable meaning it says the same thing
  whichever Focus answers. Default return is `CodingResult` (text + telemetry);
  `output=T` returns `T`.
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

## Session continuity is the author's

Two `coding` rites in one cast either share the agent's context or they do not,
and that used to be an implementation detail of the Focus. It is a declaration
now, because the right answer differs per ritual and the wrong one is invisible:

```python
await coding(prompt, session="new")        # fresh context
await coding(prompt, session="continue")   # the cast's running session
await coding(prompt, session="lint-loop")  # a named session, resumed by name
```

A retry after a failed attempt usually wants `continue` — the agent remembering
what it already tried is the whole value. A review step usually wants `new`: an
agent that helped write the code is not a reviewer of it, and silent sharing
makes that step quietly worthless while looking like it ran.

**Default `new`.** A step is a task boundary, and carrying context across one by
default contradicts what the boundary is for. Resume (0.6.0) reusing the prior
SDK session when re-entering an interrupted rite is unaffected — that is the
*same* rite continuing, not a new one inheriting.

Named sessions give a loop its own thread of memory without pinning the whole
cast to one context: a lint-fix loop remembers its own attempts while a review
rite in the same cast starts clean. `merge_ready`'s `repair` step is the shipped
example.

The grimoire records which session a rite used, so the journal, the daemon and
the Eye can all show it — and replay can reproduce it.

Three things the implementation settled that the sketch above left open:

- **`continue` is the last session *any* `coding` rite produced**, not the last
  `continue` call. The motivating case — a retry that remembers what it tried —
  follows a first attempt written as a plain `coding(...)`, which under the
  default records no thread of its own. Reading only its own kind would start
  that retry fresh while looking like it resumed.
- **It is its own parameter, not a knob on `CodingOpts`.** Everything on
  `CodingOpts` is configuration: reusing one across calls is harmless, which is
  the point of bundling them. A thread is per-call identity instead, so a
  shared `CodingOpts` carrying one would put two rites on a single agent's
  memory without either call saying so — the invisible wrong answer this
  declaration exists to remove, arriving through the door it came in. Folding
  `gate_tools` into `CodingOpts` left `coding` at four parameters, so the fifth
  costs nothing that PLR0913 charges for. `CodingOpts` forbids extras, so the
  older spelling raises rather than being silently dropped.
- **The blank check runs at call time, not construction time.** With `session`
  off the model there is no boundary left to validate at, so a `CodingOpts`
  field validator is no longer the alternative it once was — and a declaration
  the medium refuses is a `CodingSessionError`, which is a `RitualError`, which
  is what a ritual author already catches.
- **Two concurrent `coding` rites both move "the last session".** A step body
  running two mediums under a `TaskGroup` leaves `continue` after it
  last-writer-wins. Named threads are unaffected, and a name is the answer when
  it matters.

## Scope

- `vekna.folio.coding/{_pacts,_mills}.py` — `CodingOpts`, `CodingResult`,
  `Session`, `CodingOutputError`, `CodingSessionError` and the Medium itself.
- `SessionBook` on the lexicon's `RiteContext` — one per cast, holding the
  named threads and the last id any call recorded. It only remembers; which
  name a call means is the medium's vocabulary. Reached through the context
  rather than exported, since the context is what a medium already holds.
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

TUI. Multi-Focus-per-Medium. Persistence. Locks. (`folio/process` is Hand's —
[`../hand/06-process.md`](../hand/06-process.md).)

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
- Import errors in `rituals.py` — or in any submodule of a `rituals/` package —
  are reported clearly, not swallowed.
