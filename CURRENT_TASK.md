# Current Task

**Task:** finish the typing pass — fail loudly, and make the narrowings true
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — awaiting review

(Before it: `@ritual` takes a declared components model, complete through
`9e6b87e`. Its record is in that commit's version of this file.)

## Context

A review of `f19588b`, `4b7b354`, `18e7374`, `eec61a8` — three commits
strengthening types, plus their fix. Thirteen findings. Two were mine to
concede: `# ruff: ignore [rule]` is a real format under `preview = true`, and
tingle's baseline is `main`, so its number covers the whole branch rather than
those commits. The rest were a red quality gate, two half-landed behaviour
changes, and annotations the codebase contradicted.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 1 — green the gate | done | `f8e3ce9` |
| 2 — a bad config stops the command | done | `0401811` |
| 3+4 — transitions carry models; results print as JSON | done | `b379a21` |
| 5 — the focus boundary, and the door | done | `9288c54` |
| 6 — the record | done | this commit |

Gates after each step: 149 tests, 31 import-linter contracts, pylint 10.00,
mypy clean, vulture clean.

## Decisions

1. **A malformed config stops the command.** Vekna doesn't forgive. `[rituals]`
   rejects unknown keys too: tolerating a typo buys nothing when the cast that
   needed the file fails a moment later.
2. **Results print as JSON**, every ritual, not only `--prompt`.
3. **Union payloads for `@step` restored** — a merging step admits
   `Lint | Coverage`. The three commits had made them illegal while
   `Step.input_type` kept a `UnionType` arm nothing could reach.
4. **`done`/`goto` guard at runtime**, since mypy sees neither `tests/` nor any
   author's `rituals.py`.
5. **`object` where it is honest** — the focus registry and the reflection
   boundary — rather than `BaseFocus`, an empty marker the use site had to cast
   away regardless.

## Where the plan was wrong

1. **Steps 3 and 4 could not go green apart.** Rendering a result as JSON
   assumes every ritual returns a model; making them return models leaves
   assertions sitting on a repr the render replaces. Swapped, then merged.
2. **The `Any` in `_found` cost more than the `object` it replaced** — three
   new suppressions for a signature whose values are narrowed by `isinstance`
   on the next line. Kept `object`.
3. **A protocol base class deadlocked the two linters.** `@staticmethod` drew
   pylint's W0221, an instance method drew ruff's `no-self-use`. Making
   `CodingFocusProtocol.run` static on both sides satisfied both with no
   suppression.

## Suppressions

10 before this task, 10 after: one `# type: ignore` added in `_pacts.py` (no
`isinstance` against `BaseModel` typechecks under `disallow_any_expr`), one
`# pylint: disable=unused-import` removed by exporting `StringOutput` from the
lexicon's door. `object` went from 1 occurrence to 12 — the focus registry
(5), the reflection boundary (4), the loader (1), the transition guard (1),
and one JSON Schema string that is not a symbol use.

`mise run tingle` reports +30 against `main`; it was +19 before this task. The
growth is `type-object`, deliberate per decision 5.

## Open

- `# ruff: ignore [any-type]` at `coding_claude/_links.py:114` suppresses
  ANN401, which cannot fire: `"ANN"` sits in ruff's global ignore list. Left in
  place.
- The SDK stub's independence rests on import order — the test module imports
  the real `claude_agent_sdk.types` before any test replaces the parent, so the
  folio gets the real permission classes. Rewriting the stub as patches on the
  real module is Remaining 3 below.

## Remaining

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the whole 0.3.0 story.
   Bump only on explicit request.
2. **`parallel`** — owed from 0.2.0. Note the medium registry is a module-level
   singleton; that is what needs rethinking before casts can run concurrently.
3. **Manual smoke test with the real SDK.** Every `coding` test runs against a
   stub, and `coding_claude` dispatches on `runtime_checkable` protocols, which
   check attribute *presence* only. Still the one place the suite can be green
   while the integration is wrong; owed before any 0.3.0 tag.
4. **0.6.0 owes the `RiteEvent → WireMessage` projection.** `vekna.wire` is
   dormant until then — zero importers in `src/`, by design.
5. **Deferred, all deliberate:** `_parse_flags` accepts a trailing flag with no
   value; `Grimoire._events` grows unbounded and only tests read it;
   `test_probe.py` binds a real unix socket under `tests/unit/`;
   `_validate_output` catches `(ValidationError, ValueError)` where the first
   subclasses the second; `probe_daemon`'s discarded result and the empty
   `_gates.py` / `_edges.py` placeholders stay until 0.6.0.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
