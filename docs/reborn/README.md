# Reborn

The roadmap for vekna's pivot to overseeing many concurrent rituals. Common
knowledge lives once; each feature doc assumes it. One `vekna` binary, two
roles: the `vekna cast` process runs one ritual; the `vekna` daemon observes
casts, coordinates locks, owns the journal.

- [00-common.md](00-common.md) — premise, vocabulary, process model, package
  layout, layering, wire protocol, Components, config, standalone, CLI (incl.
  the Hand/Eye path), deps, resolved decisions, not-planned.

## Roadmap

1.0 ships when every feature below is ready — not when the daemon lands.

- [01-cli-reroot.md](01-cli-reroot.md) — `0.1.0` re-root CLI under `vekna tmux`;
  free top-level `vekna`.
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
- [07-tui.md](07-tui.md) — `0.7.0` Textual dashboard, multi-grimoire UI.
- [08-web.md](08-web.md) — `0.8.0` local web view (read-only → interactive).
- [09-whatsapp.md](09-whatsapp.md) — `0.9.0` WhatsApp notifications + approvals.
- [10-hardening.md](10-hardening.md) — `1.0.0` robustness, docs, example
  library, clean audits.
