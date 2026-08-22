# Docs

Two audiences, kept apart by `mkdocs.yml`'s `exclude_docs`.

**The site** — [vekna.fancysnake.dev](https://vekna.fancysnake.dev), written for
someone who has just run `pip install vekna`: [`index.md`](index.md),
[`rituals.md`](rituals.md), [`mediums.md`](mediums.md),
[`testing.md`](testing.md), [`examples.md`](examples.md),
[`safety.md`](safety.md), [`cli.md`](cli.md), and
[`architecture.md`](architecture.md), which is published as it stands for
anyone sending a patch.

**The ideas and the runbook** — written for the author, and built by nothing:

- [`releasing.md`](releasing.md) — the manual half of a release: the accounts,
  the DNS, and the order to do a tag in
- [`reborn/`](reborn/README.md) — the pivot to rituals and casts, plus
  [`reborn/common.md`](reborn/common.md), the shared context all three tracks
  assume
- [`eye/`](eye/README.md) — the surfaces that watch
- [`hand/`](hand/README.md) — the acting half
- [`done/`](done/) — what shipped, filed under the track it came from

Add a page to the site and it needs a `nav` entry in `mkdocs.yml`. Add one to a
track and it needs nothing, because the whole directory is excluded.

## How the idea files work

A track is a directory of ideas. They are not a release plan, and reading them
in order buys nothing — order is decided when work starts, not when a file is
written.

- **One file is one release's worth of work**, 13 to 21 points on the fibonacci
  scale where 1 is a typo fix that still costs a full PR, CI run and tag.
  Smaller things are grouped by topic until a file is worth shipping; a thing
  bigger than 21 is its own file and probably wants splitting.
- **No versions, no schedule, no status.** A file says what the things in it
  are, what they would ship, what is out of scope, and how you would know it
  worked.
- **The only reason to edit a file is that the scope of what is in it changed.**
  Not because something else shipped, not because the order moved.
- **Shipped moves to `done/<track>/<name>.md`** and stops being edited. The move
  is the status; `CHANGELOG.md` is the record of what actually happened.
- **No numeric prefixes.** The filename is the name of the thing.

## Release names

Every major release carries a name, and the name comes before the version does.
Contents move, and while they move a version number is a guess. A name is not.

Names come from the Vecna lore the project is named for, and each says what its
release is about: **Reborn**, the pivot from a tmux focus-switcher to rituals
and casts; **Eye**, the surfaces that watch; **Hand**, the acting half — what a
ritual can do when things go wrong, and what it can be held to.

Rules, such as they are:

- One name per **major** release. A `0.x` line is the road to a name, not a
  series of them.
- The name is documentation, not packaging. Versions stay semver; the name
  rides in the changelog heading (`## <version> — Reborn`) and the track's
  directory.
- Name a track when work on it starts. The number attaches at the tag, and
  which ideas made it in is whatever the changelog says.
