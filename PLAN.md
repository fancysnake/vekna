# PLAN — `@ritual` takes a declared components model, just as `@step` does

Source: the entrypoint is the one place in the lexicon where a signature is
reflected into a synthesized type. `@step` declares its payload as a pydantic
model and the engine validates against it; `@ritual` instead spreads loose
parameters that `create_model` stitches into a model the author never sees.

## Outcome

```python
class CoverDiff(BaseModel):
    bound: int = 3


@ritual("cover_diff")
async def cover_diff(settings: CoverDiff) -> Transition:
    return goto(measure, Uncovered(budget=settings.bound))
```

`Ritual.components` is the author's own class. CLI flags, `rituals list`,
`rituals show` and journal values all read off a model that exists in the
source, so an author can give a component a default, a validator, a
`Field(description=...)` or one of the `File`/`Directory`/`Text` annotations
without the decorator having to learn about it.

## Approved decisions

1. **Exactly one parameter, always** — mirrors `@step`'s rule literally. A
   ritual with no options declares an empty model; zero parameters is a
   `RitualDefinitionError`.
2. **The vocabulary stays "components"** — `Ritual.components`,
   `component_flags`, `components:` in `rituals show`, and the Component
   concept in `docs/reborn/` are unchanged. Only the shape changes.
3. **The word gets written down.** A component is what a ritual needs before
   it can be cast, the way a D&D spell needs its material components. That
   rationale lives nowhere in the repo, so the same word reads as five things
   — a value type (`File`), the model class (`Ritual.components`), one
   instance of it (`run_cast(components=...)`), one field (`--<component>`).
   Under the ingredient reading those are the ingredient kinds, the ingredient
   list, the ingredients brought, and one ingredient — one concept. README's
   Concepts list gains the entry that says so.

## Decisions this plan makes (flag any you disagree with)

4. **`NoComponents` ships in the lexicon.** Decision 1 means every
   option-less ritual would otherwise open with an empty class of its own —
   that is the caller being tortured for a rule's convenience. `_inits`
   already carries a private `_NoComponents` for `cast --prompt`; it becomes
   public in `_pacts` and both the prompt ritual and the tests use it.

   ```python
   @ritual("ping")
   async def ping(_: NoComponents) -> Transition:
       return done("pong")
   ```

5. **The entry boundary is guarded, like the step boundary.** `Ritual.run` is
   typed `Callable[[BaseModel], ...]`, so nothing connects the instance
   `_resolve_cast` builds to the model the ritual declared — mypy cannot see
   through that pair. `run` gets the same `isinstance` check `step` has,
   raising a new `RitualBoundaryError(RitualError)`. (`StepBoundaryError` is
   not reused: the message would name a ritual under a step's exception.)

## Steps

### Step 1 — the decorator, and every call site with it

`create_model` and its `Any`-typed field dict leave `_mills/dispatch.py`.

- `_pacts.py` — add `NoComponents` (empty `BaseModel`) and
  `RitualBoundaryError`.
- `_mills/dispatch.py` — `_component_model` becomes `_components_model`: one
  parameter or `RitualDefinitionError`; annotation must be a `BaseModel`
  subclass or `RitualDefinitionError`. `wrap.run` passes the instance straight
  to `func` after the isinstance guard. `component_flags` is untouched — it
  already reads any model's fields.
- `__init__.py` — export `NoComponents`, `RitualBoundaryError`.
- `_inits.py` — drop the private `_NoComponents` for the shared one.
- `rituals.py` — `cover_diff` declares `CoverDiff(bound: int = 3)`.
- Migrate every `@ritual` in `tests/` (11 files; the option-less ones take
  `NoComponents`, `countdown`/`echo`/`fix_demo`/`write_haiku` and friends get
  a small model each).
- New unit tests in `tests/unit/lexicon/test_engine.py`: zero parameters
  raises; two parameters raises; a non-model annotation (`bound: int`) raises;
  a mismatched instance at `run` raises `RitualBoundaryError`. The happy path
  and `components.model_fields` assertions stay, now reading the declared
  class.

Verify: `mise run test` and `mise run check` green (the check task covers
format, lint, mypy, import-linter, vulture — `mise tasks` is the authority).

### Step 2 — the record

- `README.md` — the `fix_tests` example gains its model; `vekna cast
  fix_tests --bound 5` is unchanged, which is the point worth showing.
  **Concepts** gains a Component entry, and Ritual's line stops saying
  "parameters":

  ```markdown
  - **Ritual** — a named program. Its components become `--options`.
  - **Component** — what a ritual needs before it can be cast, the way a D&D
    spell needs its material components. Typed values on its external
    interface — `File`, `Directory`, `Text`, `Url`, `GitRef` — declared as
    fields on one pydantic model and passed as `--options`.
  ```

- `docs/reborn/00-common.md` — the `fix_demo` example (~line 81) and the
  Components section (~line 253: "inspects the entrypoint signature, builds a
  Pydantic model from Component annotations" is exactly what stops being
  true). Line 268's "inputs and outputs both Components on one interface" is
  marked deferred rather than patched: `done(result)` takes `object` and
  `run_cast` returns `object`, so no output-side component exists, and under
  the ingredient reading an output is not a component at all.
- `docs/reborn/03-coding-folios.md:92` — the `cover_diff` sketch.
- `CHANGELOG.md` — under Unreleased; a breaking-shape note for `@ritual`.

Verify: `mise run check` green; `vekna rituals show cover_diff` prints the
same component line as before the change.

## Not in scope

- Renaming components to settings (decision 2).
- `@step(max_visits=N)`, annotation-gated dispatch, or anything else deferred
  in `docs/reborn/00-common.md`.
- Changing how flags parse (`_parse_flags`) or how `model_validate` coerces
  them — a declared model validates through exactly the same call.
