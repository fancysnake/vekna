# Current Task

**Task:** `@ritual` takes a declared components model, just as `@step` does
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — awaiting review

(The lexicon refactor that came before it — shrink to the SDK, satisfy the new
contracts — is complete through commit `0ef0149`; its record is in that
commit's version of this file.)

## Context

The entrypoint was the one place in the lexicon that reflected a signature into
a synthesized type: loose parameters stitched into a model by `create_model`
that the author never saw. `@step` had always declared its payload as a model
and validated against it; `@ritual` now does the same with its components.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 1 — the decorator, and every call site with it | done | `b81a39b` |
| 2 — the record | done | this commit |

Gates after each step: 139 tests, 31 import-linter contracts, pylint 10.00,
mypy clean, vulture clean. `vekna rituals show cover_diff` prints what it
printed before the change.

## Decisions

Both came out of the review conversation, and both reversed a first answer:

1. **The vocabulary stays "components".** A component is what a ritual needs
   before it can be cast, the way a spell needs its material components — so
   the model class is the ingredient list, an instance is the ingredients
   brought, and one field is one ingredient. That rationale was nowhere in the
   repo, which is what made the word read as five unrelated things. It now
   lives in README's Concepts and the `docs/reborn` glossary.
2. **Exactly one parameter, always** — the rule `@step` has. `NoComponents`
   ships in the lexicon so a ritual needing nothing does not open with an empty
   class of its own.

## Where the plan was wrong

Nowhere. Both steps landed as written.

## Open from this task

- **Fan-in** came up and was set aside: the trampoline is sequential, so a step
  merging two measurements just takes a payload carrying both halves. A real
  join — two steps concurrent, a third waiting — is a runtime feature, not a
  signature one. Deliberately not in `TODO.md`.
- Where a ritual's components and its first step's payload had the same shape,
  the test migration reused one model rather than declaring a near-duplicate
  (`Task` in `test_coding_claude.py`, `State` in `test_graph.py`).
- `docs/reborn/00-common.md`'s "inputs and outputs are both Components" is now
  marked deferred rather than deleted: nothing implements an output-side
  Component, and an output is not something a ritual needed in order to run.

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
