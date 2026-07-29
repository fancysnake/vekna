# Reborn — `1.0.0`

The roadmap for vekna's pivot to overseeing many concurrent rituals. Common
knowledge lives once; each feature doc assumes it. One `vekna` binary, three
roles: the `vekna cast` process runs one ritual; the `vekna` daemon observes
casts, coordinates locks, owns the journal; a **lich** stands in one directory
and casts on command, from a terminal or from Discord.

- [00-common.md](00-common.md) — premise, vocabulary, process model, package
  layout, layering, wire protocol, Components, config, standalone, CLI (incl.
  the Hand/Eye path), deps, resolved decisions, not-planned.

## Roadmap

1.0 ships when every feature below is ready — not when the daemon lands.

- [01-cli-reroot.md](01-cli-reroot.md) — `0.1.0` re-root CLI under `vekna tmux`;
  free top-level `vekna`. **Superseded**: the tmux subsystem it re-rooted was
  removed in 0.3.0, so the subgroup no longer exists.
- [02-lexicon-standalone.md](02-lexicon-standalone.md) — `0.2.0` lexicon SDK +
  standalone runner; `folio/flow`, `folio/shell`. `vekna cast` runs rituals.
- [03-coding-folios.md](03-coding-folios.md) — `0.3.0` `folio/coding` +
  `folio/coding_claude`; `vekna cast "<prompt>"`.
- `04` — `folio/process`, **moved to Hand** as
  [`../hand/06-process.md`](../hand/06-process.md): owning a process is
  cancellation plus bounds, and both of those are Hand's already. The slot keeps
  its number rather than closing up, so the numbering below still means what it
  did. `coding`'s session declaration, which was filed here as the other half of
  `0.4.0`, shipped in `0.3.0` instead — see
  [03-coding-folios.md](03-coding-folios.md).
- [05-locks.md](05-locks.md) — `0.5.0` locks API, `warn` default (no
  coordination yet).
- [06-vekna-daemon.md](06-vekna-daemon.md) — `0.6.0` daemon, lock coordination,
  journal, attach/replay, resume; lock default → `deny`.
- [07-lich.md](07-lich.md) — `0.7.0` the lich: a named, directory-scoped station
  that casts on command; Discord channel per lich.
- [08-hardening.md](08-hardening.md) — `1.0.0` robustness, docs, PyPI, example
  library, clean audits.
- [09-site.md](09-site.md) — `1.0.0` `vekna.dev`: landing page and user
  documentation, Astro in `www/`, shipped with the tag, not after it.
- [10-ritual-modules.md](10-ritual-modules.md) — `0.5.0` a ritual source may be
  a package the author splits as they like; recursive submodule sweep, empty
  `__init__.py`. Numbered after 09 because the slots below it are spoken for;
  the version is what orders it.

## Undecided

- [11-steps-as-dto.md](11-steps-as-dto.md) — steps return the next step as a
  value, so a return type declares a ritual's edges instead of a parser
  inferring them. Competes directly with
  [`../eye/04-graph.md`](../eye/04-graph.md)'s `@step(goes_to=[...])`; exactly
  one should be built, and both wait on rituals entering mypy's scope. Filed
  here rather than in the roadmap because it breaks the public ritual API, and
  that is a decision to take before 1.0 fixes it — not a feature 1.0 waits for.

## Parked

[`../eye/`](../eye/README.md) — **Eye** (`2.0.0`), the surfaces that watch:
Textual TUI, web view, the lich's web page, the workflow graph drawn, and the
lich's channels reshaped into adapters. Same wire, same events, another
consumer, so they park without blocking anything here. WhatsApp notifications
were dropped outright: Discord ships at 0.7.0 and does that job better.

[`../hand/`](../hand/README.md) — **Hand** (`3.0.0`), the acting half: failure
as a transition, `timeout`/`race`, cast budgets, loadable skills, and replaying
a recorded cast to check the ritual still walks its path. Engine work, filed
past 1.0 so a second syntax does not land halfway through getting the first
story finished.
