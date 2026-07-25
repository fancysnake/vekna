# PLAN — post-reborn review remediation

Source: PR [#50](https://github.com/fancysnake/vekna/pull/50) review comment of
2026-07-25 (the GLIMPSE-lens review), items P1×2, P2, P3.
Shared context: [`docs/architecture.md`](docs/architecture.md)

## Outcome

Two crashes a normal user can hit are gone, and the layer table in
`docs/architecture.md` stops being a fiction: the two violations on the branch
are fixed and an `import-linter` `layers` contract makes the table defend
itself. After this, "import boundaries enforced by import-linter" is a true
sentence rather than an aspiration.

## Approved decisions

1. **Ritual file dedupe is silent, not an error.** `[rituals] files` reads as
   additive — the name would be `extra_ritual_files` if naming an
   already-discovered `rituals.py` were a mistake. A path already loaded is
   skipped without complaint. The `already registered` error stays for the case
   it was written for: two *genuinely different* sources declaring one ritual
   name.
2. **Dedupe, not "skip implicit discovery when config names files."** The skip
   rule breaks a global `~/.config/vekna/config.toml`, which would suppress
   every project's own `rituals.py`.
3. **The shell pump reads chunks, not lines.** The 1 MiB line limit guarded
   nothing — `ShellResult.stdout` retains the full output regardless — and its
   only effect was to crash. `read()` cannot raise `LimitOverrunError`, so the
   failure mode disappears rather than being converted.
4. **`folio/shell` collapses into `_links`.** `shell()` is three lines and no
   branches; it is I/O orchestration, not business logic. The ceremony of a
   `_mills` + `_inits` pair to inject a `run_bash` that will never have a second
   implementation is not worth it here.
5. **The `register()` functions move to `_inits.py`.** They register handlers,
   which is what `docs/architecture.md` defines the inits layer to be. This is
   the ceremony worth keeping.
6. **`wire`'s codec moves to `_pacts`.** `encode_frame`/`decode_frame` are a
   codec over the DTOs beside them; this leaves `_links` importing only
   `_pacts`.

## Open approval — required before Step 4

Step 4 edits `pyproject.toml`. Per `CLAUDE.md`, configuration files are not
touched without explicit per-case approval. **Step 4 does not start until that
approval is given**; Steps 1–3 are unaffected and stand on their own.

---

## Step 1 — Loading the same rituals file twice is not an error

**Problem.** `_build_compendium` (`lexicon/_gates.py:69`) loads the discovered
`rituals.py`, then everything named in config, deduping nothing. A `.vekna.toml`
containing `files = ["rituals.py"]` beside that file makes `cast`, `rituals
list`, `rituals show` and `--help` all fail with `ritual 'demo' is already
registered` — a message naming neither source. Two config files listing one
module do the same.

**Change.** In `lexicon/_gates.py`, track loaded sources and skip repeats:

- `seen_files: set[Path]` keyed on `path.resolve()` — normalises `..` and
  symlinks so a config-relative path and a discovered one collapse to one entry.
- `seen_modules: set[str]` for `[rituals] modules`.

In `lexicon/_loader.py`, derive the `spec_from_file_location` module name from
the path instead of hardcoding `"vekna_rituals"` for every file, so two distinct
ritual files stop claiming one name.

Thread the source path into `Compendium.register` so the surviving conflict
error names both files. *(Droppable if it grows past a few lines — the dedupe is
the fix; this only improves a message.)*

**Tests.** `tests/integration/cli/` — gates are integration-tested per
`CLAUDE.md`. A `.vekna.toml` naming the discovered `rituals.py` loads one ritual
and exits 0; one module in two config files does the same; two different files
declaring one name still raise.

**Verify.** `mise run test && mise run check`, plus: a temp dir with
`rituals.py` + `.vekna.toml` naming it runs `vekna rituals list` clean.

## Step 2 — A long output line no longer crashes the cast

**Problem.** `folio/shell/_links.py:5` caps lines at 1 MiB; exceeding it raises a
bare `ValueError` from asyncio (`Separator is not found, and chunk exceed the
limit`). `_drive` catches only `FocusMissingError` and `RitualError`
(`_gates.py:268-273`), so it escapes `asyncio.run` as an unhandled traceback.
Triggered by any single-line blob: a minified bundle, base64, one-line JSON.

**Change.** Rewrite `_pump` to read fixed chunks and split lines itself:

- `await stream.read(_CHUNK)` in place of `async for raw in stream`.
- `codecs.getincrementaldecoder("utf-8")(errors="replace")` — load-bearing, as
  chunk boundaries split multi-byte UTF-8 that per-line `decode()` never met.
- Carry the trailing partial line between chunks; flush it at EOF.
- Drop `_LINE_LIMIT` and the `limit=` argument to `create_subprocess_exec`; the
  name no longer describes anything real.

**Tests.** `tests/integration/folio/test_shell.py` — a 2 MB single line is
captured whole, a following line arrives intact, exit code is 0. Verified
working against a real subprocess during review.

**Verify.** `mise run test && mise run check`.

## Step 3 — The layer table becomes true

Three independent moves. Every test imports through a package facade
(`vekna.wire`, `vekna.folio.shell`, `vekna.folio.coding`), so none of this is
visible to the suite.

**3a — `folio/shell` collapses.** Move `shell()` from `_mills.py` into
`_links.py`; delete `_mills.py`; point `__init__.py` at `_links`. Removes
`mills → links` (`shell/_mills.py:3`). The folio becomes `_links.py` +
`_pacts.py`.

**3b — `wire`'s codec moves inward.** Move `encode_frame`/`decode_frame` from
`_mills.py` into `_pacts.py`; delete `_mills.py`; `_links.py` imports `_pacts`.
Removes `links → mills` (`wire/_links.py:4`).

**3c — `register()` moves to the inits layer.** New `folio/coding/_inits.py`
(from `_mills.py:136`) and `folio/coding_claude/_inits.py` (from
`_links.py:186`); both `__init__.py` re-export from `_inits`. `_load_folios`
calls `register()` off the package, so its call site does not change.

**Verify.** `mise run test && mise run check`. Then by inspection: no
`_mills → _links` or `_links → _mills` import remains anywhere in `src/`.

## Step 4 — The contract that keeps it true *(gated on config approval)*

**Problem.** `CLAUDE.md:26` and `docs/architecture.md:3-4` both claim
import-linter enforces the boundaries. All six contracts are `type = "forbidden"`
between top-level packages; there is no `layers` contract, so the intra-package
model is documentation only. That is why the Step 3 violations survived a
thirteen-step remediation.

**Change.** One `layers` contract per package in `pyproject.toml`, listing only
the layers that package actually has. import-linter 2.12 (installed) supports
same-layer siblings via `:`, which expresses the table exactly — `links` and
`mills` are peers that may not import each other:

```toml
[[tool.importlinter.contracts]]
name = "lexicon layers"
type = "layers"
layers = [
    "vekna.lexicon._gates",
    "vekna.lexicon._links : vekna.lexicon._mills",
    "vekna.lexicon._specs",
    "vekna.lexicon._pacts",
]
```

Note for review: a `layers` contract permits `_gates → _links`, which is exactly
the exception `docs/architecture.md:59-62` already documents for the lexicon, so
the two agree. It does not express "gates may not import links" for a package
that has no such exception — `lexicon` is the only package with a gates layer,
so nothing is lost today.

If the reflection helpers (`_dispatch`, `_graph`, `_loader`) resist placement,
they stay unlisted rather than forcing a layer that misdescribes them.

**Verify.** `mise run check` reports 10 contracts kept, 0 broken. Then confirm
the contract bites: reintroduce `from ._links import run_bash` in a scratch
copy, see it break, revert.

## Step 5 — Reconcile the record

Update `docs/architecture.md` (layout section: `folio/shell` and `wire` lose
`_mills`, two folios gain `_inits`) and `CHANGELOG.md` `[Unreleased]`. Refresh
`CURRENT_TASK.md`.

If Step 4 is declined, this step instead **softens the enforcement claim** in
`CLAUDE.md:26` and `docs/architecture.md:3-4` to say the layer table is a
convention — leaving a false claim in the docs is not an option either way.

---

## Not in scope

Carried from the review, deliberately deferred:

- **`_parse_flags` trailing flag** (`_gates.py:223`) — `vekna cast r --name`
  silently yields `{'name': ''}`. Real, but a separate cut.
- **`Grimoire._events` unbounded** — nothing in `src/` reads `.events`; only
  tests do. Wants a decision about whether the grimoire is a live journal or a
  buffer, which belongs with the 0.6.0 daemon.
- **`test_probe.py` binds a real unix socket under `tests/unit/`** — should move
  to integration.
- **`_validate_output` catches `(ValidationError, ValueError)`** — the former
  subclasses the latter.
- **Real-SDK smoke test for `coding_claude`.** Structural `runtime_checkable`
  dispatch checks attribute presence only, and every test uses a stub. Still the
  one place the suite can be green while the integration is wrong; owed before
  any 0.3.0 tag, as `CURRENT_TASK.md` already records.
