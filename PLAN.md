# PLAN — rituals.py grows up: exercise the branch through real rituals

Source: a read of the whole branch against `rituals.py`. The branch is green —
149 tests, 31 contracts, pylint 10.00, mypy and vulture clean — and `cover_diff`
exercises roughly a third of what a ritual author can reach for. The component
types, `decide`, structured output, `CodingOpts`, `gate_tools`,
`focus_options`, union payloads and `max_steps` are live in `src/` and reached
only by unit tests, never by a ritual travelling CLI → components → step →
medium.

## Outcome

Three more rituals in `rituals.py`, each one something this project would
actually cast, chosen so its natural shape lands on the unexercised surface —
including two mediums in flight at once, merged when both are done.
`rituals.py` stops being the only Python in the repo that no gate reads. Two
latent bugs — both found by probing, neither by reading — are fixed before the
rituals that would trip them are written.

## Findings this plan implements

0. **Two mediums can already run at once; two *steps* cannot.** `asyncio` inside
   a step is all it takes — each medium opens its own rite under the same
   parent, because a Task copies the contextvar. Verified by casting it. No
   engine change, no fork/join: "start both, wait for both" is a step body.
   Two things the probes settled, and both shape what gets written:
   - **`TaskGroup`, not `gather`.** When one medium raises, `gather` leaves the
     sibling running: the step unwinds first and the sibling's rite closes
     *after its own parent* (`✗ with_gather` then `✗ slow`), so the journal
     nests wrongly. `TaskGroup` cancels the sibling inside the group, and the
     rites close in order.
   - **A concurrent rite's output is unattributable on an append-only sink.**
     `_format` indents a delta by its rite's depth alone, so two siblings at the
     same depth interleave with nothing to tell them apart. Your call on this:
     the sink's capability decides. A TUI owns its screen and can re-render in
     place; stdout and an IM cannot, so there the rite's output waits for the
     rite to finish.
1. **`component_flags` cannot name an optional component.**
   `_mills/dispatch.py:127` reads `field.annotation.__name__`. For
   `note: str | None` that renders `[--note <Union>]` on 3.14, and on
   3.11–3.13 `types.UnionType` has no `__name__` at all — `rituals list`,
   `cast --help` and `rituals show` raise `AttributeError`. CI runs the full
   3.11–3.14 matrix and stays green only because no ritual has an optional
   union component. Every ritual below wants one.
2. **`rituals.py` is outside every gate.** `check` lints `src tests`, mypy reads
   `src`, pytest reads `tests/`.
3. **Rituals that call `coding` cannot run in the suite.** Cost and
   non-determinism. So what is *demonstrated* and what is *verified* get
   separated on purpose: the suite drives `rituals list` / `rituals show` over
   the real file, which is every path except the agent call itself.

## Assumptions — correct me and I will change them

- **Three rituals, `triage` included.** Dropping it would cost `Url`,
  `allowed_tools` and `gate_tools`.
- **Step 1 belongs in this task**, engine change and all: it is the reason the
  rituals can be written naturally rather than around a bug.
- **`merge_ready` reports; it does not push.** No ritual in this file performs
  an irreversible git action.
- **Suppression count does not grow.** Step 1 relocates the existing
  `# type: ignore [misc]` from `component_flags` into the helper that earns it;
  10 before, 10 after.
- **The `typing.Optional[X]` spelling stays unsupported**, matching
  `_is_model_union`, which already accepts only `X | Y`.

## Steps

### Step 1 — component_flags tells the truth about optional components

- `_mills/dispatch.py` — a `_type_name(annotation: object) -> str` helper.
  A `UnionType` drops `NoneType` and joins the rest with `|`, so `str | None`
  reads `<str>` and `File | None` reads `<Path>`; anything else falls back to
  `__name__` via one `getattr` laundered through `name: object`, which is where
  today's ignore moves; a missing name stays `value`. No `get_origin` — its
  return is `Any` and would cost a second suppression.
- `tests/unit/lexicon/test_step.py` — a `TestComponentFlags` class: optional
  union, multi-member union, plain type, generic alias, no annotation.
- `tests/integration/cli/test_rituals.py` — the fixture ritual gains an
  optional union component, so `rituals list` renders it on every Python in
  the matrix.

Verify: `mise run test`, `mise run check`.

### Step 2 — concurrent rites read correctly on an append-only sink

`StandaloneRenderer` writes to a plain stream: no cursor, no re-render. So a
rite that has a live sibling holds its deltas and emits them just before its own
`✓`, which puts every line next to the rite it came from. A rite with no sibling
streams exactly as it does today, so `cover_diff`'s output does not change.

- `_links/standalone.py` — `_rites` also remembers each rite's parent. At
  `RiteBegan` a rite is marked *held* when it has an open sibling, or when its
  parent is held; a held rite's deltas accumulate instead of printing, and a
  held child flushes into its parent's buffer so a whole subtree emits as one
  block when the outermost held rite ends. The `↳`/`▶` line still prints
  immediately — you see both gates start.
- `tests/unit/lexicon/test_renderer.py` — sequential output unchanged;
  two siblings' deltas grouped, each before its own `✓`; a held rite that ends
  with `✗` still flushes what it had; a nested medium inside a held sibling.

Not built here: any notion of a sink that *can* re-render. The TUI is 07 and the
IM sinks are 08/09; this step only stops the one existing sink from lying.

Verify: `mise run test`, `mise run check`, plus a cast of the concurrent ritual
from step 4 read by eye.

### Step 3 — `review`, a diff read against a base ref

Components `base: GitRef = "main"`, `only: File | None = None`,
`focus: Text = ""`. Steps `collect` → `judge`.

- `collect` shells `git diff <base>...HEAD` with `stream=False` — a diff is
  noise, not progress — and carries the text plus `sha256_of(only)` when a file
  was named, pinning the review to the bytes reviewed.
- `judge` calls `coding(output=Judgement, opts=CodingOpts(system=...),
  focus_options=ClaudeOptions(permission_mode="dontAsk",
  allowed_tools=["Read", "Grep", "Glob"], effort="high"))` and composes
  `done(Review)` from what came back plus the provenance the agent must not
  invent. **Not `permission_mode="plan"`**, as this plan first said: the SDK
  documents plan mode as executing no tools at all, so the reviewer could not
  read `CLAUDE.md`. `dontAsk` with an allowlist is read-only enforced —
  everything outside the list is denied without a prompt.

Covers: `GitRef`, `File`, `Text`, an optional component, structured output,
`CodingOpts`, `ClaudeOptions`, `stream=False`, `sha256_of`.

Verify: `mise run test`, `mise run check`, `vekna rituals show review`.

### Step 4 — `merge_ready`, both gates at once, babysat to green

Components `bound: int = 3`; `@ritual("merge_ready", max_steps=...)`.

- `gates` starts `mise run prcheck` and `mise run test` **together** in an
  `asyncio.TaskGroup` and waits for both. The two suites take minutes each and
  neither reads the other's output, so running them in sequence wastes the
  wall-clock for nothing. Both results are merged, so one cast tells you
  everything that is red — not the first thing that is red.
- The merge routes on what failed: `LintFailure | TestFailure | BothRed`, the
  union arm restored in `b379a21` and used by nothing until now.
- `repair` admits all three shapes, hands the failures to `coding`, and returns
  to `gates` with the budget decremented.
- On green, `decide(...)` before stopping. It reports; it does not push.

Covers: two mediums in flight at once and merged, a three-member union payload,
`decide` (bool), `max_steps=`, a two-source budget loop — and it is the ritual
that reads step 2's rendering.

Verify: `mise run test`, `mise run check`, `vekna rituals show merge_ready`, and
one real cast — the gates are this project's own and cost nothing but time.

### Step 5 — `triage`, an issue or PR read from a link

Components `link: Url`, `bound: int = 2`.

- `read` calls `coding(output=Triage, focus_options=ClaudeOptions(
  allowed_tools=["WebFetch"], permission_mode="plan"))`.
- `route` uses `decide(options=["fix", "file", "ignore"])`; the `fix` arm calls
  `coding(gate_tools=["Bash"])`, so a shell command needs an answer from you.

Covers: `Url`, `allowed_tools`, `decide(options=)`, `gate_tools`.

Verify: `mise run test`, `mise run check`, `vekna rituals show triage`.

### Step 6 — put `rituals.py` under a gate

- `mise.toml` — `black`, `black-check`, `ruff`, `ruff-fix` and `codespell` take
  `rituals.py` alongside `src tests`.
- `tests/integration/cli/test_project_rituals.py` — drives `rituals_list` and
  `rituals_show` over the repo's own `rituals.py` from the repo root: every
  ritual loads, every flag renders, every step graph resolves. No agent runs.
- mypy and vulture stay on `src`: vulture calls every ritual dead, and mypy
  under this config may demand suppressions the rules forbid without approval.
  If mypy is clean on `rituals.py` it joins; if it is not, it stays out and the
  record says why.

Verify: `mise run test`, `mise run check`.

### Step 7 — the record

- `rituals.py`'s module docstring, which documents only `cover_diff` today.
- `README.md` — concurrency inside a step is worth a Concepts line, since
  nothing in the docs says a step may hold two mediums at once.
- `CHANGELOG.md`, `CURRENT_TASK.md`.

## Not in scope

- **Parallel *steps*.** Not needed for any of this: concurrency lives in a step
  body. `Transition` stays `Goto | Done` and `run_cast` stays a sequential loop.
- **A non-`RitualError` from a medium escapes as a traceback.** The gather probe
  surfaced it: `_drive` catches `FocusMissingError` and `RitualError`, so a
  `RuntimeError` — from an author's own code or from the SDK — dumps a stack and
  exits 1 with no `cast failed:` line. Pre-existing, arguably right for an author
  bug, wrong for an SDK failure. Reported, not fixed; it wants its own decision.
- Running `review` or `triage` against the real SDK. That is `CURRENT_TASK.md`
  Remaining 3, still owed, still manual. `merge_ready`'s gates are free to cast.
- `NoComponents` in `rituals.py`: the `--prompt` path already carries it, and a
  no-component ritual here would exist only to name the class.
- The medium-registry singleton, and anything else owed to 0.5.0+.
