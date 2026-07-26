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

Names come from the Vecna lore the project is named for, and each says what its
release is about: **Reborn**, the pivot from a tmux focus-switcher to rituals
and casts; **Eye**, the surfaces that watch. `hand` — the acting half of the
[Hand and Eye](reborn/00-common.md) easter egg — is unspoken for, and is the
name waiting for a release about doing rather than seeing.

Rules, such as they are:

- One name per **major** release. The `0.x` line is not a series of names; it is
  the road to Reborn.
- The name is documentation, not packaging. Versions stay semver, `pip install
  vekna` means exactly what it says, and the name rides along in the changelog
  heading (`## 1.0.0 — Reborn`) and the track's directory.
- Name a track when work on it starts, not when it ships. That is the whole
  point: `docs/eye/` was nameable long before anyone knew it would be 2.0.0.

## Contents

- [`architecture.md`](architecture.md) — layer map, layout, patterns, drift flags
- [`reborn/`](reborn/README.md) — Reborn (1.0.0): the roadmap, and the common
  knowledge every feature doc in it assumes
- [`eye/`](eye/README.md) — Eye (2.0.0): the visual surfaces, parked until
  Reborn ships
