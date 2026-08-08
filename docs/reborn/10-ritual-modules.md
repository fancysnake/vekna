# Feature — Rituals as modules

**Version:** `0.4.0` — **shipped.**

> Filed a slot lower and built before [05-locks.md](05-locks.md), so it took the
> number `folio/process` left free on its way to Hand rather than sharing one
> with a feature that is not written. Two things the spec did not say, settled
> while building: a directory counts as a source only with an `__init__.py`, at
> **every** level — `pkgutil` yields a directory without one as nothing at all,
> so a namespace-package level would go unswept in the same silence this feature
> exists to remove — and the cwd is what goes on `sys.path` for
> `[rituals] modules`, which is literally what `PYTHONPATH=.` said.

See [00-common.md](00-common.md) — Components, config, package layout.

## Goal

A ritual source is one file, and it grows with the rituals in it. `rituals.py`
is 507 lines holding four rituals; the shipped `examples/pr_sweep.py` is 704
holding two. Prompts, models, helpers and steps interleave, so reading one
ritual means skipping past the other three.

Let a ritual source be a **package**, split however its author likes, with the
engine finding every ritual and every step inside it and `__init__.py` staying
empty as the rules elsewhere require.

The layout is the author's business. This doc is about the engine stopping
getting in the way of it.

## What ships

- **`rituals/` discovered like `rituals.py`.** Walking up from the cwd finds a
  directory as readily as a file.
- **`rituals.py` beside `rituals/` is an error**, not a precedence rule. Both
  name a ritual source and neither says it is the one meant.
- **Directory sources load as real packages** — `import_module`, not
  `spec_from_file_location`.
- **The ritual root's parent goes on `sys.path`** before the import, so
  `PYTHONPATH=.` stops being a precondition for `[rituals] modules`.
- **Every submodule is swept**, recursively, for `Ritual` and `Step` objects.
  `__init__.py` stays empty; no re-export list to keep in sync.
- **Step name collisions across sources are an error**, not a silent win for
  whichever loaded first.

## Why each one

Measured against today's engine, on the layout it is meant to support:

```text
rituals/
  __init__.py
  components.py
  prompts.py
  steps.py        from .components import Diff; from .prompts import REVIEW
```

**Discovery.** `_find_rituals_file` builds `directory / "rituals.py"` and asks
`.is_file()`. A directory is never a candidate, so the layout is reachable only
by naming it in `.vekna.toml`. Once both are candidates one directory can hold
both, and a precedence rule would answer that silently: a half-finished move
into `rituals/` would keep casting the file it was moved out of, and the rituals
the author is editing would simply not be there. That is the same shape as the
truncated graph below, so it takes the same answer the step collision does — the
cast stops, naming both paths, and the author deletes or renames one. Walking up
is unaffected: a parent directory's source is still found when the nearer one
holds neither.

**Package identity.** The `files` route cannot load a package at all.
`spec_from_file_location` gives the module a synthetic dotted-less name, so the
first relative import fails:

```text
ModuleNotFoundError: No module named 'vekna_rituals_probe'
```

A directory source must therefore route to `load_rituals_module`, not
`load_rituals_file`. The two loaders stop being interchangeable.

**`sys.path`.** The `modules` route works — but only with `PYTHONPATH=.`.
`vekna` is a console script, so `sys.path[0]` is the venv's `bin`, and the
project root is on the path of exactly nothing:

```console
$ vekna rituals list
No module named 'rituals'
```

Asking every author to export `PYTHONPATH` before a cast is a worse door than
the one file it replaces.

**The sweep.** `_found` reads `vars(module)`, which for a package is the
`__init__.py` namespace and nothing below it. A step the `__init__` does not
name is invisible to the compendium — and because an unregistered step is
treated as a leaf, `rituals show` truncates *silently*:

```text
steps:
  (start) → collect
  collect → judge          ← judge not re-exported; graph stops, no warning
```

Re-exporting `judge` restores `judge → (done)`. A truncated graph and a
finished one look identical, which is the worst shape a bug can take in a
feature whose whole job is telling the operator what a ritual does. Requiring
the re-export would also contradict the project's own rule that `__init__.py`
stays empty, so the sweep is what makes the layout idiomatic rather than
merely possible.

**Collisions.** `register_step` is `setdefault`, and its comment justifies the
choice: *"Steps are collected for `rituals show` only, so a name collision
across modules is not worth an error — the first definition wins."* That holds
while every step is in one file, where a duplicate name is a visible mistake.
Across ritual packages it stops holding: `cover_diff/steps.py:measure` and
`pr_sweep/steps.py:measure` are both natural names, and the loser vanishes —
`rituals show pr_sweep` would draw the other ritual's step. Registration keys
on the source that declared it, and a genuine collision names both, as
`Compendium.register` already does for rituals.

## Layout is the author's

The engine ships no opinion beyond "a package works". For the record, what the
two real sources measure:

| Source | Lines | Declared | Rituals | Per ritual |
|---|---|---|---|---|
| `rituals.py` | 507 | 308 | 4 | ~125 |
| `examples/pr_sweep.py` | 704 | 473 | 2 | ~350 |

And what those declarations are:

| | `rituals.py` | `pr_sweep.py` |
|---|---|---|
| steps | 41% | 49% |
| prompts | 24% | 18% |
| models | 20% | 14% |
| helpers | 8% | 13% |

Two things follow, and both are guidance for the example library
([08-hardening.md](08-hardening.md)) rather than anything the engine enforces:

- **Split by ritual before splitting by kind.** Across the four rituals in
  `rituals.py` exactly one symbol is shared (`Bound`, by `CoverDiff` and
  `MergeReady`); every prompt, model and helper belongs to exactly one ritual.
  Splitting by kind means three files open to read one step. A ritual is a
  module until it wants to be a package — `~125` lines does not, `~350` does.
- **Helpers are a fourth kind.** `components`/`prompts`/`steps` does not cover
  the code: `_said`, `_red`, `_complaint`, `_HEADLINE`, `_gh_view`, `_prs`,
  `_wanted`, `_arc` are none of the three, and at 13% of `pr_sweep.py` they are
  a file rather than a rounding error.

```text
rituals/
  shared.py          Bound
  cover_diff.py      ~70   ─┐
  review.py          ~110   ├ one file each
  merge_ready.py     ~130   │
  triage.py          ~140  ─┘
  pr_sweep/          ~350  ─┐ earned the second level
    __init__.py             │
    prompts.py              │
    mills.py                │
    steps.py               ─┘
```

## Scope

- `lexicon/_links/loader.py` — directory discovery, the `sys.path` insertion,
  the recursive submodule sweep, routing a directory source to the module
  loader.
- `lexicon/_inits.py` — `_find_rituals_file` returning a package as readily as
  a file, refusing a directory that holds both, and `_build_compendium`
  dispatching on which it got.
- `lexicon/_mills/engine.py` — `register_step` keyed by source, collision an
  error naming both.

## Out of scope

- ~~**Rituals in mypy's scope.**~~ **Done, separately.** `SRC_PATHS` is
  `src rituals.py` and the file is clean. It had reported 22 errors: 13 the
  `@step`/`@ritual` contravariance issue, since fixed by giving the decorators
  the author's own model; 8 `Any` leakage from the `TaskGroup` in
  `merge_ready.gates`; and one real bug (`decide(options=[...])` returning `str`
  into `Triaged.took: Literal[...]`). A ritual *package* — the subject of this
  document — still has to be named in `SRC_PATHS` to get the same treatment.
- **Steps as DTOs**, with step values appearing only in return statements —
  [11-steps-as-dto.md](11-steps-as-dto.md). Undecided, and competing with
  [`../eye/04-graph.md`](../eye/04-graph.md): it is a change to the ritual model
  rather than to how one is loaded.
- **Parallel across steps.** Not happening. Steps never run concurrently;
  concurrency stays inside a step body as plain `asyncio`, as
  `merge_ready.gates` already does.

## Acceptance

- A `rituals/` package split into submodules is found by walking up from the
  cwd, with no `.vekna.toml` and no `PYTHONPATH`.
- Its `__init__.py` is empty, and `rituals list` still names every ritual.
- `rituals show` draws the full graph for a ritual whose steps live in a
  submodule the `__init__` never mentions.
- Relative imports between submodules work, including from `__init__.py`.
- A single-file `rituals.py` keeps working unchanged, and a `.vekna.toml`
  naming `files` or `modules` keeps working unchanged.
- Two sources declaring a step of the same name fail with an error naming both.
- A directory holding both `rituals.py` and `rituals/` fails with an error naming
  both paths, and the upward walk stops there rather than skipping to a parent.
- `mise run check` and `mise run test` pass.
