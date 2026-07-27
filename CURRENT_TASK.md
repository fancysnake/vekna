# Current Task

**Task:** rituals.py grows up — exercise the branch through real rituals
**Plan:** [`PLAN.md`](PLAN.md) — approved, complete
**Branch:** `vekna-reborn`
**Phase:** IMPLEMENT complete — awaiting review

(Before it: the typing pass, complete through `311d597`. Its record is in that
commit's version of this file.)

## Context

`cover_diff` exercised about a third of what a ritual author can reach for. The
component types, `decide`, structured output, `CodingOpts`, `gate_tools`,
`focus_options`, union payloads and `max_steps` were live in `src/` and reached
only by unit tests — never by a ritual travelling CLI → components → step →
medium. Three more rituals now do, each one something this project would
actually cast.

Two engine bugs were fixed first, and both were found by casting rather than
reading. Two more surfaced the same way and are recorded below rather than
fixed.

## Progress against PLAN.md

| Step | State | Commit |
| --- | --- | --- |
| 1 — a flag names the type it takes | done | `1a973c4` |
| — the same, on 3.11 | done | `8a334ab` |
| 2 — concurrent rites read correctly | done | `bc84657` |
| 3 — `review` | done | `ec1d0c3` |
| 4 — `merge_ready` | done | `1f3e520` |
| 5 — `triage` | done | `24c71f8` |
| 6 — `rituals.py` under a gate | done | `106e60d` |
| 7 — the record | done | this commit |

Gates after each step: 167 tests, 31 import-linter contracts, pylint 10.00,
mypy clean, vulture clean. The suite was also run under Python 3.11 from a
throwaway venv, since the 3.11 bug in step 1 was invisible on 3.14.

## Decisions

1. **Concurrency lives in a step body, not in the engine.** `asyncio.TaskGroup`
   over two mediums is all "start both, wait for both" needs: a Task copies the
   contextvar, so each medium opens its own rite under the same parent.
   `Transition` stays `Goto | Done` and `run_cast` stays a sequential loop. No
   fork/join.
2. **`TaskGroup`, not `gather`.** When one medium raises, `gather` leaves the
   sibling running and its rite closes *after its own parent* — the journal
   nests wrongly. `TaskGroup` cancels inside the group and the rites close in
   order.
3. **The sink's capability decides how concurrent output reads.** stdout cannot
   re-render, so a rite with a live sibling waits and emits in one block. A TUI
   can re-render and will want the opposite; that belongs to 07/08/09.
4. **`dontAsk` plus an allowlist is how you get a read-only agent** — not
   `permission_mode="plan"`, which the SDK documents as executing no tools at
   all. A reviewer in plan mode cannot read the `CLAUDE.md` it needs to judge
   against. The README recommended the wrong one; fixed.
5. **`gh` through `shell`, not an agent holding `WebFetch`.** It reads private
   repositories, returns JSON rather than HTML, and needs no judgement — so it
   belongs where it is deterministic and free. (`WebFetch` also turned out to be
   unavailable here, but the design reason stands on its own.)
6. **One approved suppression, per-file and per-rule:** RUF029 on `rituals.py`.
   A `@ritual` entrypoint must be `async def` because `Ritual.run` is typed
   `Awaitable[Transition]`, and one that only maps components onto the first
   payload has nothing to await. The rule is right about the function and wrong
   about the contract, and it fires on every ritual anyone writes.

## Where the plan was wrong

1. **Step 1 was two bugs, not one.** `File | None` rendered `<Annotated>` for a
   different reason than `str | None` rendered `<Union>` — and then a third
   reason on 3.11, where the typing union is not a `UnionType` at all. Only the
   first was fixed before the tests said so.
2. **`permission_mode="plan"` was in the plan and is wrong.** See decision 4.
3. **`triage` was planned around `WebFetch`.** Casting it found the tool denied
   with the tool allowlisted, denied domain-scoped, and denied under
   `bypassPermissions`. `Read` under the same `dontAsk` allowlist works, which
   is what ruled the folio out as the cause and left `review` standing. Reshaped
   onto `gh`, which is the better instrument regardless.
4. **`triage` had a dead component.** `bound: int = 2`, on a ritual that does
   not loop. Removed.
5. **mypy could not join the gates.** It reports 22 errors on `rituals.py`, and
   almost none are the author's: `@step` is typed
   `Callable[[BaseModel], Awaitable[Transition]]`, so every concrete step — one
   taking `Diff`, `Uncovered`, `Fetched` — is contravariance-incompatible. See
   Remaining 6.

## Suppressions

11 after this task, 10 before: RUF029 on `rituals.py` per decision 6. Step 1
relocated one `# type: ignore [misc]` rather than adding one — the `getattr`
laundered through `name: object` needed none, and reading `field.annotation`
did.

`mise run tingle` reports +39 against `main`; it was +30 before this task. The
+9 is `ruff-per-file-ignores` +1 (RUF029) and `type-object` +8 — the `object`
annotations in `_type_name`, `_is_union` and `_plain_name`, which are what keep
the untyped annotation read from spreading. Deliberate, and the same call as the
previous task's decision 5. Tingle is not in `check` or `prcheck`; its baseline
is `main`, so its number covers the branch rather than this task.

**Correction to the previous record.** It listed
`# ruff: ignore [any-type]` at `coding_claude/_links.py:114` as suppressing a
rule that cannot fire, because "`ANN` sits in ruff's global ignore list". It does
not: the global `ignore` is `COM812`, `CPY`, `D1`, `PLC2701`, and `ANN` is only
in `per-file-ignores` for `tests/**`. Removing the comment makes ruff report
`any-type` at that line, so it is load-bearing.

## Open

- **A non-`RitualError` from a medium escapes as a traceback.** `_drive` catches
  `FocusMissingError` and `RitualError`, so a `RuntimeError` — from an author's
  own code or from the SDK — dumps a stack and exits 1 with no `cast failed:`
  line. Arguably right for an author bug, wrong for an SDK failure. Wants its
  own decision.
- **`decide`'s prompt collides with the rite's `✓` when stdin is a pipe.**
  `_confirm` leaves the cursor after `[y/n] `; on a real TTY the answer's own
  newline fixes it, so this only shows non-interactively. Cosmetic, unfixed.
- **`test_probe.py` binds a real unix socket**, and on 3.14 its transport
  teardown intermittently raises inside `__del__`, which pytest attributes to
  whichever test is running when GC fires. Seen once in ~10 runs. Already owed
  (Remaining 5).
- **`WebFetch` is unavailable in this environment** — denied even under
  `bypassPermissions`. Nothing in `src/` depends on it now.

## Remaining

1. **Release bump.** `CHANGELOG.md` `[Unreleased]` holds the whole 0.3.0 story.
   Bump only on explicit request.
2. **`parallel` across steps** — owed from 0.2.0, and now clearly *not* needed
   for concurrency, which lives in a step body. What it would buy is fan-out the
   engine schedules and the grimoire nests as siblings; the module-level medium
   registry is still the thing to rethink first.
3. **Manual smoke test with the real SDK.** Materially advanced, not closed:
   `review`'s two non-agent paths, `merge_ready` (four casts, all three union
   arms) and `triage` (both failure paths, two real casts) all ran here, plus
   `cast -p`. `review`'s agent step and `triage`'s `fix`/`file` arms have not.
4. **0.6.0 owes the `RiteEvent → WireMessage` projection.** `vekna.wire` stays
   dormant until then — zero importers in `src/`, by design.
5. **Deferred, all deliberate:** `_parse_flags` accepts a trailing flag with no
   value; `Grimoire._events` grows unbounded and only tests read it;
   `test_probe.py` binds a real unix socket under `tests/unit/`;
   `_validate_output` catches `(ValidationError, ValueError)` where the first
   subclasses the second; `probe_daemon`'s discarded result and the empty
   `_gates.py` / `_edges.py` placeholders stay until 0.6.0.
6. **`@step`'s type is not usable by authors under strict mypy.** Its parameter
   is `Callable[[BaseModel], Awaitable[Transition]]`, which no concrete step
   satisfies. A `TypeVar` bound to `BaseModel` would fix the common case; a
   union-payload step is harder. Until then, `rituals.py` stays out of mypy.

## Notes

- Stay on `vekna-reborn`; commit after each green step.
- 3.11 is worth running before trusting anything that reads annotations. Build a
  venv outside the project — mise's `_.python.venv` activates `.venv`, whose
  interpreter shadows `MISE_PYTHON_VERSION`, so the CI-style invocation silently
  runs 3.14 here.
