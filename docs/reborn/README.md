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
- [04-process-folio.md](04-process-folio.md) — `0.4.0` `folio/process`
  (dev-server use case).
- [05-locks.md](05-locks.md) — `0.5.0` locks API, `warn` default (no
  coordination yet).
- [06-vekna-daemon.md](06-vekna-daemon.md) — `0.6.0` daemon, lock coordination,
  journal, attach/replay, resume; lock default → `deny`.
- [07-lich.md](07-lich.md) — `0.7.0` the lich: a named, directory-scoped station
  that casts on command; Discord channel per lich.
- [08-hardening.md](08-hardening.md) — `1.0.0` robustness, docs, PyPI, example
  library, clean audits.

## Parked

[`../eye/`](../eye/README.md) — **Eye** (`2.0.0`), the visual surfaces: Textual
TUI, web view, the lich's web page. Same wire, same events, another consumer, so
they park without blocking anything here. WhatsApp notifications were dropped
outright: Discord ships at 0.7.0 and does that job better.
