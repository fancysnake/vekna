# Feature — ritual defaults: a component answered once per repo

**Version:** `0.8.0` — **planned**, beside [13-ritual-craft.md](13-ritual-craft.md),
whose provenance it shares.

See [00-common.md](00-common.md) — discovery and configuration, Components,
Tome.

## Where this came from

A tome ships `pr_check` to several repositories. One of its components is the
base branch, and the answer is a property of the repository, not of the run:
`main` here, `master` there, forever. Every cast — nightly, from cron, from a
lich — types it again, and every crontab, every README, every operator's shell
history carries a copy of a constant.

A pydantic field default does not solve it. `base_branch: str = "main"` is the
*ritual author's* answer, baked into the tome, and the repo that says `master`
cannot change it without forking the tome. The missing default is the
**operator's**, and the operator's file is `.vekna.toml`, which already sits in
the repo and already says which rituals exist there.

## Goal

A component whose value is fixed per repository is written once in
`.vekna.toml` and never passed on the command line again.

## What ships

One config table, keyed by ritual name:

```toml
[defaults.pr_check]
base_branch = "main"
max_prs = 3
```

Values are merged under the parsed flags before the components model validates,
so a flag still wins:

```python
values = {**defaults.get(name, {}), **_parse_flags(flags)}
the_ritual.components.model_validate(values)
```

TOML scalars arrive typed — `max_prs = 3` is an `int`, not `"3"` — which is
strictly better than the CLI path, where every value is a string pydantic
coerces. Nothing in the merge needs to know that.

**Precedence, per key:** CLI flag → project `.vekna.toml` → global
`~/.config/vekna/config.toml`. The same order the rest of configuration already
reads in, and per key rather than per table, so a global default survives a
project table that overrides one of its neighbours.

**A required component that config answers is no longer missing.** That is the
whole point, and it makes `rituals show` lie: a field printed `--base-branch
<str>` reads as something the operator must supply. `show` prints the effective
value and where it came from:

```text
components:
  --base-branch <str>  = main (.vekna.toml)
  --pull-request <int>
```

`rituals list` and `--help` keep their one-line shapes and are left alone; the
place a person goes to ask what a ritual needs is `show`.

## Errors

- **A key the ritual does not declare** — `[defaults.pr_check] base_brnach` —
  fails the cast, naming the config file, the ritual and the key. The
  components model would otherwise ignore the extra and the operator would
  watch a ritual use a default they believe they set.
- **A ritual name nothing registers** is *not* an error. A global config holds
  defaults for tomes that are not installed in every directory it applies to,
  and a directory with no `pr_check` is not a mistake to report.
- Both checks happen at cast time, against the compendium that was built. A
  config that does not parse still stops the command where it always did.

## Out of scope

- **A table that applies to every ritual.** `[defaults] base_branch = "main"`
  reads well and cannot be checked — a key no ritual declares is
  indistinguishable from one that a ritual not installed here declares. Repeat
  the line per ritual; revisit if a repo ever has enough rituals for that to
  hurt.
- **Env overrides for components.** `VEKNA_*` exists for one-shot settings
  (`VEKNA_STANDALONE_LOCKS`); a component already has a one-shot spelling, and
  it is the flag.
- **Defaults in `trial`.** A ritual test constructs its components model
  directly and never reads a config file. Nothing to do, and a test that
  changed behaviour with the developer's `.vekna.toml` would be a bug.
- **Secrets.** `.vekna.toml` is committed. Same posture as
  [`safety.md`](../safety.md): a component holding a credential is passed at
  the call, not written down.

## Where it lands

- `Config` in `vekna/lexicon/_pacts.py` gains
  `defaults: dict[str, dict[str, object]]`. The table is open by construction —
  its keys are ritual names and its values are the author's fields — so unlike
  `[rituals]` it cannot forbid extras, and the cast-time check above is what
  replaces that.
- `_build_library` in `vekna/lexicon/_inits.py` already reads every config file
  in precedence order; `_Library` carries the merged mapping out beside the
  compendium, with the file each key came from, for the error and for `show`.
- `_resolve_cast` merges; `_component_lines` renders.

## Acceptance

- `vekna cast pr_check --pull-request 7` casts with the base branch the repo
  configured, and `--base-branch release` still beats it.
- A misspelt key in `[defaults.*]` fails the cast naming the file, not silently.
- A global config naming a ritual this directory does not have casts fine.
- `vekna rituals show pr_check` says which components are already answered and
  by which file.
