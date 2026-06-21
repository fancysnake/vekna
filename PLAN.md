# PLAN — Feature 0.2.0: Lexicon SDK + standalone runner

Source spec: [`docs/reborn/02-lexicon-standalone.md`](docs/reborn/02-lexicon-standalone.md)
Shared context: [`docs/reborn/00-common.md`](docs/reborn/00-common.md)

## Outcome

Ship the rituals SDK as a working program with **no daemon** and **no agent
provider**. A user writes `rituals.py` with `folio/shell` + `folio/flow`, runs
`vekna cast <ritual>`, and gets a structured terminal experience driven by the
standalone renderer.

## Key design decisions (flag for approval before relying on them)

1. **Core code never imports `lexicon`/`folio` — not even `gates`.** The `cast`
   subcommand appearing under `vekna` and the `gates` package importing
   `lexicon` are independent; (2) is never needed. The cast runtime lives
   entirely inside `vekna.lexicon` (`lexicon/_gates.py` is its own entry
   surface, e.g. `main(argv)`). The single dispatch point is the **composition
   root** `inits/cli.py:run()` — wiring, which is `inits`' job — via a dynamic
   `importlib`:

   ```python
   def run() -> None:
       if len(sys.argv) > 1 and sys.argv[1] == "cast":
           importlib.import_module("vekna.lexicon").main(sys.argv[2:])  # cast process
           return
       init_command()()  # daemon-side click tree — never touches lexicon
   ```

   A string-name `importlib` import is invisible to import-linter's static
   graph, so the contract stays green — backed by the real process split (the
   cast process loads lexicon; the daemon never does). `gates` stay 100%
   lexicon-free, even dynamically.

2. **`cast` loads `rituals.py` in-process — no subprocess for the ritual.**
   Each `vekna cast …` shell command is already its own OS process; that *is*
   the cast process (blast radius = one invocation). It `importlib`-loads
   `rituals.py` (file → `spec_from_file_location`/`exec_module`; dotted module →
   `import_module`), the `@ritual`/`@medium` decorators register into the
   Compendium as an import side effect, then we resolve the requested name and
   `await` the coroutine. No fork, no re-exec, no pooling. (`folio/shell`'s bash
   Focus spawns a subprocess — that's a medium running a command, unrelated to
   ritual loading.)

3. **`rituals.py` is a self-sufficient, lintable Python module.** It imports
   everything explicitly (`from vekna.lexicon import ritual, RiteContext`,
   `from vekna.folio.flow import decide, repeat`, …). The runner **injects
   nothing** into the module namespace — no magic globals. A user can run
   `ruff`/`mypy`/`pylint` on their `rituals.py` and it resolves against vekna's
   shipped public types (`py.typed`). Consequences:
   - `lexicon` and `folio.*` `__init__.py` **are** the public surface
     (re-exports + `__all__`) — the *external public-API package* exception to
     the empty-`__init__` rule. Daemon-side GLIMPSE layers keep empty
     `__init__`.
   - Decorators must be **typing-transparent** (ParamSpec / overloads) so user
     files type-check under strict mypy (`disallow_any_expr`, …) — no
     `Any`-erasure. A real Step 2/3 constraint.
   - Component annotations (`bound: Text`) are the typed contract the user sees
     and what CLI flags derive from.
   - Linting never executes the file (ruff/mypy/pylint are static); registration
     side effects only fire at real runtime load.

4. **Lexicon + folios use underscored GLIMPSE-flat** (`_pacts.py`, `_specs.py`,
   `_mills.py`, `_links.py`, `_gates.py`); public surface only in
   `__init__.py` via `__all__`. `vekna.lexicon.components` is a public module.

5. **`vekna.wire` is the single schema home.** Pydantic DTOs + newline-JSON
   framing. Imports nothing internal. Both the cast process and (later) the
   daemon import only `wire`.

## Configuration changes needing explicit per-case approval

Per project rules, I will **not** touch these without a go-ahead at that step:

- **`pyproject.toml` import-linter contracts** — new contracts for `wire`,
  `lexicon`, `folio.flow`, `folio.shell`, and the core ⊥ lexicon/folio
  forbidden rules. (Steps 1, 2, 6, 7.)
- **`pyproject.toml` dependency** — `tomli` (>=2,<3) for `.vekna.toml` parsing
  on Python 3.10 (stdlib `tomllib` is 3.11+). Needed at Step 5. Will confirm
  whether to add `tomli` or raise the Python floor to 3.11 instead.
- **`[project.scripts]` / coverage omit** — no change expected; will flag if it
  comes up.

## Ordered steps

Each step ends green: `mise run check` (format + lint + import-linter + mypy)
and `mise run test` pass. Commit after each. Stay on branch `reborn`.

### Step 1 — `vekna.wire` (DTOs + framing)

- `wire/__init__.py` (public `__all__`), `wire/_pacts.py`: Pydantic models for
  every kind in the common wire table (`CastHello`, `CastGoodbye`,
  `GrimoireBegin/End`, `RiteStarted/Delta/Finished`, `DecideRequested/Resolved`,
  `ApprovalRequested/Resolved`, `AskRequested/Resolved`, lock events) + a
  tagged-union envelope + framing helpers (`encode_frame`, `decode_frame`,
  async `read_frames`).
- **Config approval:** add import-linter contract for `wire` (forbidden from all
  `vekna.*` internal layers/packages).
- Tests: `tests/unit/wire/` — DTO round-trip, envelope discrimination, framing
  encode/decode incl. partial/multi-line buffers.

### Step 2 — `vekna.lexicon` errors + components + public skeleton

Model: `@ritual` entrypoint + `@step` task graph + `goto`/`done` transition
trampoline (see `00-common.md` "Ritual model").

**Delivered (as built):**

- `lexicon/_pacts.py`: errors only — `RitualError`, `WorkflowBudgetExceededError`.
- `lexicon/components.py` (public): `File`, `Directory`, `Text` (+ `TextSpec`),
  `Url`, `GitRef`, `sha256_of`. (`Email` deferred — needs `email-validator` dep;
  `Process`/`Executable` deferred to `folio/process`.)
- `lexicon/__init__.py`: public `__all__` skeleton — the two errors (decorators
  + transitions added in Step 3).
- **Config approval:** import-linter contracts (this step) — see request below.
- Tests: `tests/unit/lexicon/test_components.py`.

**Moved to Step 3** (their types couple to the engine / the `Step` type
`@step` produces — `Goto.target` can't be cleanly typed without it under strict
`disallow_any_explicit`): `Transition`/`Goto`/`Done`, `goto`/`done`,
`Medium`/`Focus`/`RiteContext`, and `_specs.py` (`DEFAULT_MAX_STEPS`, socket-name
template, env vars — deferred to first consumer to avoid vulture-unused).

Step 3 is **split** — the typing of dynamic dispatch needed an isolated
reflection module (`_dispatch`, scoped mypy override), so transitions + `@step`
landed first (3a), then the engine (3b).

### Step 3a — transitions + `@step` (DELIVERED)

- `lexicon/_pacts.py` (extend): `Transition`/`Goto`/`Done` (+ `goto`/`done`),
  the `Step` type (`run: Callable[[object], Awaitable[Transition]]`,
  `input_type`), errors (`RitualDefinitionError`, `StepBoundaryError`).
- `lexicon/_dispatch.py`: the reflection boundary (mypy override) — `@step`
  reads the single-payload annotation and wraps the func into a `Step` whose
  `run` validates the incoming payload (`isinstance`) then awaits the body.
  User steps annotate `-> Transition` (lintable; they `return goto(...)`/`done(...)`).
- mypy per-module override for `vekna.lexicon._dispatch` (approved).
- Tests: `tests/unit/lexicon/test_step.py`.

### Step 3b — `@ritual` + Grimoire + Compendium + engine (PENDING)

- `lexicon/_pacts.py` (extend): `Medium`/`Focus`/`RiteContext` protocols.
- `lexicon/_specs.py`: `DEFAULT_MAX_STEPS` (+ socket-name template / env vars
  when their consumers land in Steps 4–5).
- `lexicon/_dispatch.py` (extend) / `lexicon/_mills.py`: `@ritual` (entrypoint —
  builds the Component interface Pydantic model from its signature, fires the
  opening transition); the **Grimoire** (event log of `vekna.wire` DTOs, via an
  injected clock); the **Compendium** registry (ritual name → entrypoint); the
  **step engine** — trampolines step→step on each `goto`, narrates
  `RiteStarted`/`RiteFinished` per hop, enforces the **loop budget**
  (`@ritual(max_steps=…)` + `@step(max_visits=…)`, `DEFAULT_MAX_STEPS` fallback →
  `WorkflowBudgetExceededError`), validates `done` result vs the ritual output
  type, stops on `done`. Each step validates its own input on entry (boundary
  enforcement); cross-wiring is caught there.
- Tests: `test_grimoire.py`, `test_compendium.py`, `test_ritual.py`,
  `test_step_engine.py` — registration, trampoline + event assembly, budget
  aborts a cycle, `done` termination. Pure logic, no I/O.

### Step 4 — `vekna.lexicon` links (probe + standalone renderer) (DELIVERED)

- `lexicon/_links.py`: `probe_daemon` (Any-free socket liveness check — sync
  `socket` connect + timeout via `asyncio.to_thread`; silent + non-hanging when
  absent) + `default_socket_path`; **`StandaloneRenderer`** (structured events →
  stdout; stdin `decide`/`approve`/`ask` with bounded retry →
  `StandalonePromptError`). `StandalonePromptError` added to `_pacts`.
- Tests: `test_renderer.py` (StringIO stdin/stdout), `test_probe.py`
  (absent → silent/no hang; reachable → true; default path).
- **Deferred to 0.6.0:** the **wire client** (streaming events to the daemon) —
  its consumer/test harness is the daemon. The probe covers client-side
  connection detection now. The background re-probe loop (daemon arriving
  mid-cast) also lands at 0.6.0; 0.2.0 probes once at startup.

### Step 5 — `vekna.lexicon` entry (`main`) + `inits` dispatch (DELIVERED, split 5a/5b)

**5a** (commit `8d64972`): `lexicon/_gates.py` cast runner `main(argv) -> int` —
discover `rituals.py` (walk up from cwd), `importlib`-load + scan for `@ritual`
(in relaxed `_dispatch.load_rituals_file`), parse `--flags` → Component model
(pydantic-coerced), probe daemon socket (silent/no-hang), drive `run_cast`,
render the grimoire to stdout, exit code. `inits/cli.py` `run()` argv-dispatches
`cast` to `vekna.lexicon.main` via the 3-line `inits/cast.py` shim (dynamic
`import_module` — invisible to import-linter; decision #1) under a scoped mypy
override. `StandaloneRenderer` resolves `sys.stdout/stdin` at instantiation.

**5b** (commit `8f675b5`): `.vekna.toml` config — `read_config` parses
`[rituals].modules/files` from the nearest project `.vekna.toml` (walk up) +
`~/.config/vekna/config.toml`; the runner loads the implicit `rituals.py` plus
configured files/modules into one Compendium. `tomllib` on 3.11+, `tomli` below
(declared dep, `python_version < '3.11'` marker). TOML read stays in relaxed
`_dispatch`.

- Tests: `tests/integration/test_cast.py` — `vekna cast` drives a real
  `rituals.py` end-to-end (exit 0, structured grimoire), unknown ritual / no
  rituals → exit 2, `.vekna.toml` files augmentation. Real `vekna cast` smoke
  verified.

### Step 6 — medium machinery + `vekna.folio.flow` (DELIVERED, split 6a/6b)

**6a** (commit `6c187f4`): the medium seam in lexicon — `Channel` protocol
(`_pacts`, satisfied by `StandaloneRenderer`), `RiteContext` (grimoire + channel
+ parent rite id) in an ambient contextvar, `current_rite()`, and `@medium`
(typing-transparent `ParamSpec` decorator, relaxed `_dispatch`) that brackets a
nested `medium` rite via `medium_rite`. `run_cast` now takes a `channel` and
sets `parent_id` per step so mediums nest under their step.

**6b** (commit `67a54a8`): `vekna.folio.flow` — `decide`/`approve`/`ask`
`@medium`s reaching `current_rite().channel`. import-linter: `folio.flow`
contract (forbidden from core; may import lexicon + wire); `vekna.folio` added to
`core-no-lexicon` + `wire` forbidden lists.

- **Deferred:** `parallel` (concurrent rites in the grimoire tree — complex, not
  acceptance-critical). `branch`/`repeat`/`attempt` are NOT mediums (fold into
  `goto`/guards/`try-except`).
- Tests: `tests/unit/folio/flow/test_flow.py` (decide+approve+ask round-trip via
  stdin); `test_medium.py` (nesting, category, current_rite outside cast).
  Real `vekna cast` with `decide` smoke-verified (stdin-piped).

### Step 7 — `vekna.folio.shell` (DELIVERED, commit `221e3e4`)

- `folio/shell/`: `shell(command, cwd=…)` `@medium` → bash focus
  (`_links.run_bash`, asyncio `bash -c` subprocess) → `ShellResult(stdout,
  stderr, exit_code)` (`_pacts`).
- import-linter: `folio.shell` contract (forbidden from core + `folio.flow`);
  `folio.flow` forbidden extended with `folio.shell` (folio ⊥ folio both ways).
- Tests: `tests/integration/test_shell.py` — real bash, stdout/zero-exit +
  stderr/nonzero-exit. (No `noqa` needed; `create_subprocess_exec` didn't trip
  bandit S-rules.)

### Step 8 — Example + end-to-end acceptance (DELIVERED, commit `d465502`)

`examples/rituals.py` ships `fix_demo` (shell + decide + guarded repeat loop:
`check`→`decide`→`apply_fix`→`check`). `tests/integration/test_acceptance.py`
casts a copy to completion. Verified with real `vekna cast fix_demo --bound 3`
(exit 0, grimoire to stdout, decide from stdin, `.fixed` created).

**ORIGINAL Step 8 spec:**

- `examples/rituals.py`: at least one ritual using `shell` + `decide` +
  `repeat` (e.g. `fix_demo` taking a `--bound` Component).
- Integration test: `vekna cast fix_demo --bound 3` runs end-to-end, prints a
  structured Grimoire to stdout, exits 0; `decide`/`approve`/`ask` prompt on
  stdin and route back; absent-socket probe is silent.
- Final full `mise run check` + `mise run test`.

## Conventions discovered (Step 1 — apply to all later steps)

- **Public-API `__init__.py`** re-exports its underscored modules with a
  **relative** import (`from ._pacts import …`) — absolute (`from vekna.wire._pacts`)
  trips ruff `PLC2701`; relative is clean, no `noqa`/config change.
- **Class-based tests** use `@staticmethod` methods (no `self`) to satisfy ruff
  `PLR6301`, matching the existing suite.
- **Pydantic discriminated unions**: use `pydantic.Discriminator("kind")` in
  `Annotated[...]`, not `Field(discriminator=...)` — `Field()` is typed `Any`
  and trips strict mypy `disallow_any_expr`.
- Drive async code from sync tests via `asyncio.run(...)` (no `asyncio_mode`
  set; pytest is strict).
- Gate command: `mise run check` (black, ruff-fix, codespell, mypy, `il`,
  pylint, vulture) + `mise run test`.

## Acceptance (from the spec)

- [ ] `vekna cast fix_demo --bound 3` runs end-to-end, structured Grimoire to
      stdout, exits 0.
- [ ] `decide` / `approve` / `ask` prompt on stdin and route the answer back.
- [ ] Probing the absent daemon socket is silent and does not hang.
- [ ] `mise run check` and `mise run test` pass.

## Out of scope (do not build)

Daemon. Coding medium. Claude. TUI. Persistence. Locks (0.5.0).
`vekna cast "<prompt>"` sugar (0.3.0).
