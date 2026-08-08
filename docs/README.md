# Docs

## Release names

Every major release carries a name, and the name comes before the version does.
Contents move — locks arrived, WhatsApp was dropped, the lich was invented in a
single conversation — and while they move, a version number is a guess. A name
is not. Work is discussed, planned and filed under the name from the day it
starts, and the number is attached at the tag.

| Name | Version | Track | State |
|------|---------|-------|-------|
| **Reborn** | `1.0.0` | [`reborn/`](reborn/README.md) | in progress |
| **Eye** | `2.0.0` | [`eye/`](eye/README.md) | parked |
| **Hand** | `3.0.0` | [`hand/`](hand/README.md) | parked |

Names come from the Vecna lore the project is named for, and each says what its
release is about: **Reborn**, the pivot from a tmux focus-switcher to rituals
and casts; **Eye**, the surfaces that watch; **Hand**, the acting half — what a
ritual can do when things go wrong, and what it can be held to. Eye and Hand are
the two halves of the [Hand and Eye](reborn/00-common.md) easter egg, doing the
job that easter egg was always describing.

Rules, such as they are:

- One name per **major** release. The `0.x` line is not a series of names; it is
  the road to Reborn.
- The name is documentation, not packaging. Versions stay semver, `pip install
  vekna` means exactly what it says, and the name rides along in the changelog
  heading (`## 1.0.0 — Reborn`) and the track's directory.
- Name a track when work on it starts, not when it ships. That is the whole
  point: `docs/eye/` was nameable long before anyone knew it would be 2.0.0.

## Roadmap

Every feature, what it is filed as, and whether it exists. **Shipped** links to
the release in [`CHANGELOG.md`](../CHANGELOG.md) that carried it — the changelog
is what happened, this is what is meant to; a row is shipped here only once the
changelog says so. Each feature doc repeats its own status in its header and
nowhere else.

### Reborn — the pivot to rituals and casts

| Feature | Version | Status |
|---------|---------|--------|
| [CLI re-root](reborn/01-cli-reroot.md) | `0.1.0` | [shipped](../CHANGELOG.md#010---2026-06-01), then superseded |
| [Lexicon SDK + standalone runner](reborn/02-lexicon-standalone.md) | `0.2.0` | [shipped](../CHANGELOG.md#020---2026-06-28) |
| [`folio/coding` + `folio/coding_claude`](reborn/03-coding-folios.md) | `0.3.0` | [shipped](../CHANGELOG.md#030---2026-07-27) |
| [Rituals as modules](reborn/10-ritual-modules.md) | `0.4.0` | [shipped](../CHANGELOG.md#040---2026-08-08) |
| [Trial: testing rituals](reborn/12-trial.md) | `0.4.0` | [shipped](../CHANGELOG.md#040---2026-08-08) |
| [The site](reborn/09-site.md) | `0.4.1` | in progress |
| [Locks API](reborn/05-locks.md) | `0.5.0` | planned |
| [Vekna daemon](reborn/06-vekna-daemon.md) | `0.6.0` | planned |
| [Lich](reborn/07-lich.md) | `0.7.0` | planned |
| [1.0 hardening](reborn/08-hardening.md) | `1.0.0` | in progress |
| [Steps as DTOs](reborn/11-steps-as-dto.md) | — | undecided |

### Eye — the surfaces that watch

Parked until Reborn ships. Unscheduled within `2.x`.

| Feature | Status |
|---------|--------|
| [Textual TUI](eye/01-tui.md) | planned |
| [Web view](eye/02-web.md) | planned |
| [The lich's web surface](eye/03-lich-web.md) | planned |
| [The workflow graph, drawn](eye/04-graph.md) | undecided — competes with [steps as DTOs](reborn/11-steps-as-dto.md) |
| [Surfaces as adapters](eye/05-channels.md) | planned |

### Hand — the acting half

Parked until Reborn ships. Unscheduled within `3.x`.

| Feature | Status |
|---------|--------|
| [Failure as a transition](hand/01-failure.md) | planned |
| [`timeout` and `race`](hand/02-timeout-race.md) | planned |
| [Cast budgets](hand/03-budgets.md) | planned |
| [Skills](hand/04-skills.md) | planned |
| [Replay](hand/05-replay.md) | planned |
| [`folio/process`](hand/06-process.md) | planned |

## Contents

- [`architecture.md`](architecture.md) — layer map, layout, patterns, drift flags
- [`reborn/`](reborn/README.md) — the common knowledge every Reborn feature doc
  assumes, and the notes on how its numbering came to be what it is
