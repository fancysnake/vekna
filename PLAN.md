# PLAN — finish the typing pass: fail loudly, and make the narrowings true

Source: the review of `f19588b`, `4b7b354`, `18e7374`, `eec61a8` and your
answers to it. Two of the thirteen findings were mine to concede (`# ruff:
ignore` is a real format under `preview = true`; tingle's baseline is `main`,
so the +19 is the whole branch, not those commits). What is left is a red
quality gate, two half-landed behaviour changes, and a set of annotations the
codebase contradicts.

## Outcome

`done`/`goto` take pydantic models or nothing, and say so at runtime rather
than in a comment mypy never checks outside `src/`. A malformed `.vekna.toml`
stops the command instead of quietly loading no rituals. A cast's result
prints as JSON. Nothing in the lexicon is typed `BaseFocus` or
`dict[str, type]` to avoid writing `Any` or `object` honestly.

## Answers this plan implements

1. **Config: fail the command.** Vekna doesn't forgive.
2. **Result: JSON for every ritual**, not only `--prompt`.
3. **Union payloads for `@step` are restored** — `A | B` is legal again.
4. **`done()`/`goto()` guard at runtime**, since mypy sees neither `tests/`
   nor `rituals.py` nor anyone's `rituals.py`.
5. **`object` where it is honest, `Any` where it is honest** — `BaseFocus`
   goes, `dict[str, type]` becomes `Any`.
6. **Suppressions stay.** None are removed by overruling you; one disappears
   in step 5 because the import that needed it stops existing.

## Assumptions — correct me and I will change them

- **`[rituals]` forbids unknown keys; the top-level table does not.** Your note
  was that tolerating a typo buys nothing when the next `vekna cast` fails
  anyway. Top-level extras stay legal because `[locks]` is specified for 0.5.0
  and would otherwise start failing every config that carries it.
- **A cast with no result prints `result: null`** — JSON all the way rather
  than a bare `None`.
- **`ClaudeCodingFocus` declares `CodingFocusProtocol` as a base.** The
  CLAUDE.md rule asks for it, and with `BaseFocus` gone it is the only thing
  type-checking that the focus still fits the medium.
- **`# ruff: ignore [any-type]` at `_links.py:127` stays**, though `"ANN"` is
  in ruff's global ignore list, so it suppresses a rule that cannot fire.

## Steps

### Step 1 — green the gate

`mise run check` fails at `eec61a8`: pylint 9.99, `W0621` twice.

- Delete `PermissionResultAllow` / `PermissionResultDeny` from `_sdk_stub`
  (`test_coding_claude.py:125-131`) and their two `stub.` assignments. They
  are dead: `_links.py` imports both from `claude_agent_sdk.types`, and the
  test module's own top-level import of the real submodule populates
  `sys.modules` before any test replaces the parent — so the folio already
  gets the real classes.
- Commit ruff's pending `--fix` edits to `_links.py` and the test.

Verify: `mise run test`, `mise run check` — both green, pylint back to 10.00.

### Step 2 — a bad config stops the command

- `_pacts.py` — `RitualsConfig` gains `model_config = ConfigDict(extra="forbid")`
  and its fields become `list[str] = []` rather than `list[str] | None = None`,
  which is what forces the `or []` dance at the call site.
- `_links/loader.py` — `read_config` returns `Config`, never `None`. A
  `ValidationError` is re-raised as `RitualDefinitionError(f"{path}: {error}")`
  so the message names the file. `RitualError` is already in `_LOAD_ERRORS`, so
  `_drive` and `_compendium_or_usage` turn it into exit 2 on stderr for free.
- `_links/loader.py` — `_found(namespace: dict[str, Any])`, owning the `Any`
  that `vars(module)` actually returns.
- `_inits.py:103-107` — back to three lines, no `None` dance.
- `tests/unit/lexicon/test_config.py` — the two "reads as empty" cases become
  "raises", keeping one case for a config with no `[rituals]` table at all
  (still legal, still empty). Plus a CLI test in
  `tests/integration/cli/test_rituals.py`: a malformed `.vekna.toml` exits 2
  and names the file.

Verify: `mise run test`, `mise run check`.

### Step 3 — results print as JSON

- `_inits.py:308` — `result: {model.model_dump_json()}`, `result: null` when
  there is none.
- Assertions follow: `test_cast.py:157`, `test_coding_claude.py:365,400,413,425`,
  `test_acceptance.py`.

Verify: `mise run test`; `vekna cast -p` prints `result: {"output":"haiku done"}`.

### Step 4 — transitions carry models or nothing, and enforce it

- `_mills/dispatch.py` — `_get_param_annotation` splits in two. A `@ritual`
  still requires exactly one `BaseModel` subclass. A `@step` accepts that or a
  `UnionType` whose every member is a `BaseModel` subclass or `NoneType`;
  anything else stays a `RitualDefinitionError`. `Step.input_type` keeps its
  `type[BaseModel] | UnionType`, which stops being dead.
- `_pacts.py` — `done()` and `goto()` raise `RitualBoundaryError` for a value
  that is neither a `BaseModel` nor `None`. `Done.result` and `Goto.payload`
  keep their annotations, which the guard now makes true.
- Call sites that the guard would break, all of them today's counter-examples:
  `README.md:41,43` (`done("green")`, `done("gave up")`),
  `test_engine.py:72,162`, `test_coding_claude.py:35,78`, and `echo` in
  `test_cast.py`.
- New tests: a union-payload step routed both ways; `done("x")` and
  `goto(step, "x")` each raise.

Verify: `mise run test`, `mise run check`.

### Step 5 — the focus boundary, and the door

- `_pacts.py` — delete `BaseFocus`. `engine.py`'s registry returns to `object`
  in its three signatures; `coding/_mills.py:93` keeps its
  `cast("CodingFocusProtocol", ...)`, which was the necessary one all along.
- `coding_claude/_links.py` — `ClaudeCodingFocus(CodingFocusProtocol)`.
- `lexicon/__init__.py` — export `StringOutput`. `coding/_mills.py` then
  imports it from `vekna.lexicon` instead of reaching into another package's
  `_pacts`, and `CodingFocusProtocol` goes back behind `TYPE_CHECKING` where a
  `cast("...")` needs nothing at runtime — which is what removes the
  `# pylint: disable=unused-import`, rather than any judgement about it.

Verify: `mise run test`, `mise run check`, and `mise run tingle` reported
(not gated — its baseline is `main`, so its number reflects the branch).

### Step 6 — the record

- `CHANGELOG.md` — the config failure mode, the JSON result, models-only
  transitions.
- `README.md` — Concepts line for transitions if the example changes shape.
- `CURRENT_TASK.md`.

## Not in scope

- Rewriting the SDK stub as patches on the real module (`CURRENT_TASK.md`
  Remaining 3). Step 1 leaves the stub healthy; the drift risk stays.
- Extending mypy over `tests/` — you chose the runtime guard instead.
- Removing any suppression by argument.
