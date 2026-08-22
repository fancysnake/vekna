# Casting a ritual you did not write

See [common.md](common.md) — Components, discovery and configuration,
`rituals list` / `rituals show`.

Four things that close the gap between the person who wrote a ritual and the
person who casts it: worked examples to read, a manual the ritual carries
itself, a check that its graph is honest, and a way to stop typing the same
constant. Independent of each other; grouped because they answer one question.

## An example library worth reading

Someone who has installed vekna should be able to read a ritual that does
something they recognise, and cast it. The four in this repository are engine
exercises before they are examples; none of them fans out over a work list, and
the workflows vekna is aimed at all do.

Five rituals, each in its own file, each stating the exact permission set it
needs — a recommendation nobody can act on is not a recommendation:

- **PR triage.**
- **Test-and-fix loop.**
- **Migration babysitter.**
- **Merge babysitter.**
- **A queue ritual** — the missing shape, and the one every unattended workflow
  turns out to be. As found in practice: a run-level accumulator; a fresh
  per-item payload that *dies with the item*, so budgets reset by construction;
  items dropped at the listing rather than skipped later, so a parked item is
  never checked out, never counted, never in the report; the queue ordered by
  staleness; and one terminal report that every ending routes to.

Layout follows the guidance the docs already give: split by ritual before
splitting by kind, and let a ritual stay one file until it earns a package.

Out of scope: rituals that need an account nobody reading the page has, a ritual
per provider, anything that cannot be read in one sitting.

## The ritual's docstring is its manual

A real ritual opens with 55 lines of operator documentation: what its labels
mean, what ends a branch versus what ends the run, why it asks nothing, how to
park an item for a month. It is the best artifact in the file, and no vekna
surface displays a word of it — `@ritual` drops `func.__doc__`, and `Ritual` has
nowhere to put it.

Capture the docstring on `Ritual`, print it under `rituals show`, and take its
first line as the summary in `rituals list`.

This is an exception to the house rule against docstrings, and worth stating as
one: a ritual's entry docstring is not commentary on the code, it is the
interface — the same claim `--help` makes. Making it load-bearing is what keeps
it true.

Out of scope: step docstrings, markdown rendering, any reformatting beyond what
the terminal needs.

## `vekna rituals check`

The graph `rituals show` draws is read off each step's source text, matching
`goto` calls whose first argument is a bare name. A `goto` inside a helper is
invisible to it, so authors write every `goto` out at its call site to stay
drawable — a rule recorded in a comment and enforced by nothing.

One subcommand over the AST walk `graph.py` already does. It reports:

- a step in the compendium that no `goto` reaches;
- a step whose source yields no `goto` and no `done` — either it is dead or its
  transition is hidden in a helper;
- a `goto` naming a target the compendium never registered;
- two sources declaring the same step name.

Best-effort, like the drawing it shares its reader with, and it says so: a
computed target is not an error, it is a thing the check cannot see. Exit
non-zero on a finding, so a ritual library can gate on it.

Out of scope: making the graph exhaustive. That is a change to how a step
declares its edges, and it is [steps-as-dtos.md](steps-as-dtos.md).

## A component answered once per repo

A tome ships one ritual to several repositories. One of its components is the
base branch, and the answer is a property of the repository, not of the run:
`main` here, `master` there, forever. Every cast — nightly, from cron, from a
lich — types it again, and every crontab, every README, every operator's shell
history carries a copy of a constant.

A pydantic field default does not solve it. `base_branch: str = "main"` is the
*ritual author's* answer, baked into the tome, and the repo that says `master`
cannot change it without forking the tome. The missing default is the
**operator's**, and the operator's file is `.vekna.toml`.

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

Errors:

- **A key the ritual does not declare** — `[defaults.pr_check] base_brnach` —
  fails the cast, naming the config file, the ritual and the key. The components
  model would otherwise ignore the extra and the operator would watch a ritual
  use a default they believe they set.
- **A ritual name nothing registers** is *not* an error. A global config holds
  defaults for tomes that are not installed in every directory it applies to.
- Both checks happen at cast time, against the compendium that was built.

Out of scope:

- **A table that applies to every ritual.** `[defaults] base_branch = "main"`
  reads well and cannot be checked — a key no ritual declares is
  indistinguishable from one that a ritual not installed here declares. Repeat
  the line per ritual.
- **Env overrides for components.** `VEKNA_*` exists for one-shot settings; a
  component already has a one-shot spelling, and it is the flag.
- **Defaults in `trial`.** A ritual test constructs its components model
  directly and never reads a config file. A test that changed behaviour with the
  developer's `.vekna.toml` would be a bug.
- **Secrets.** `.vekna.toml` is committed. Same posture as
  [`../safety.md`](../safety.md): a component holding a credential is passed at
  the call, not written down.

Where it lands: `Config` in `vekna/lexicon/_pacts.py` gains
`defaults: dict[str, dict[str, object]]` — open by construction, since its keys
are ritual names, so unlike `[rituals]` it cannot forbid extras and the
cast-time check replaces that. `_build_library` already reads every config file
in precedence order; `_Library` carries the merged mapping out beside the
compendium, with the file each key came from. `_resolve_cast` merges;
`_component_lines` renders.

## Acceptance

- Each example casts end to end against a real repository, with the credentials
  its page names and nothing more; the queue example survives one item failing.
- `vekna rituals show <ritual>` prints what its author wrote for its operator,
  and `rituals list` shows the first line beside the name.
- `vekna rituals check` fails a ritual whose `goto` is hidden in a helper, and
  reports a computed target as unseeable rather than as an error.
- `vekna cast pr_check --pull-request 7` casts with the base branch the repo
  configured, and `--base-branch release` still beats it; a misspelt key in
  `[defaults.*]` fails the cast naming the file; a global config naming a ritual
  this directory does not have casts fine.
- `mise run fullcheck` passes.
