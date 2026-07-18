# Feature — `folio/coding` + `folio/coding_claude`

**Version:** `0.3.0`

See [00-common.md](00-common.md) for Medium/Focus/Component and Component
output direction.

## Goal

First action Medium with a real third-party Focus. The `coding` Medium defines
the portable shape of "ask an agent to do work"; the Claude Agent SDK is the
first Focus, shipped as an extra so it's optional. `vekna cast "<prompt>"`
returns as sugar for a one-rite cast using this Medium.

## What ships

- `vekna.folio.coding` — `coding` Medium with portable params (`prompt`,
  `model`, `system`, `cwd`); `CodingFocusProtocol`. No SDK import. Output shape
  declared per call site via `output=` (see common); default return is agent
  telemetry, telemetry lands in the grimoire entry.
- `vekna.folio.coding_claude` — `ClaudeCodingFocus` implementing the protocol
  via `claude-agent-sdk`. Pulled in by `pip install vekna[coding-claude]`.
  `_links.py` is the only place importing `claude-agent-sdk`.
- Tool-use gate as a `decide` round-trip: the SDK's `can_use_tool` callback
  emits `DecideRequested` over the wire; the daemon routes to the active
  surface; the answer returns; the future resolves. Same pattern in standalone
  (stdin).
- `--auto-approve <tool>` flag and per-Focus options
  (`focus_options=ClaudeOptions(...)`) for Claude knobs (skills, agent presets)
  without polluting the Medium.
- `vekna cast "<prompt>"` — sugar constructing a one-rite cast on the `coding`
  Medium with the default Claude Focus; attaches if the daemon is up,
  standalone otherwise.
- `vekna rituals list` / `vekna rituals show <ritual>` — discover `rituals.py`,
  list registered rituals with signatures. Ritual parameters → Click flags via
  `inspect.signature`.

## Scope

- `vekna.folio.coding/{_pacts,_mills,_gates}.py` + `register`.
- `vekna.folio.coding_claude/{_pacts,_links}.py` + `register`.
- Compendium gains `try/except ModuleNotFoundError` loading for
  `coding_claude` — missing extra surfaces only when a ritual reaches for the
  Medium.
- `gates/cli/click/cast.py` — `vekna cast "<prompt>"`, `vekna rituals
  list/show`. Discovers `./rituals.py` via importlib.
- Example: a real `fix_and_commit` ritual using `coding` + `shell` + `decide`
  in a budget-guarded `goto` loop.

## Out of scope

TUI. Multi-Focus-per-Medium. Persistence. Locks. (`folio/process` is v0.4.0.)

## Acceptance

- `pip install vekna[coding-claude]`, then `vekna cast "write a haiku"` prints
  streamed output, exits 0. Without the extra, same command exits with a clear
  "missing Focus" message.
- Motivating pattern works end-to-end:

  ```python
  class Attempt(BaseModel): budget: int
  class Report(BaseModel):  committed: bool

  @ritual("fix_and_commit")
  async def fix_and_commit() -> Transition:
      return goto(fix, Attempt(budget=5))

  @step
  async def fix(a: Attempt) -> Transition:
      await coding(prompt="fix the failing tests")
      r = await shell("mise run test")
      if r.ok and await decide("tests green — commit?"):
          return goto(commit, a)
      if a.budget == 0:
          return done(Report(committed=False))
      return goto(fix, Attempt(budget=a.budget - 1))

  @step
  async def commit(a: Attempt) -> Transition:
      await coding(prompt="commit the changes")
      return done(Report(committed=True))
  ```

- `vekna rituals list` shows registered rituals and their typed flags.
- Import errors in `rituals.py` are reported clearly, not swallowed.
