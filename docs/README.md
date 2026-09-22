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
- [`common.md`](common.md) — the shared context every idea issue assumes:
  premise, vocabulary, process model, wire, CLI surface, resolved decisions

Add a page to the site and it needs a `nav` entry in `mkdocs.yml`; the files
above are listed in `exclude_docs` instead.

## How the ideas work

A track is a GitHub milestone, and an idea is an issue in it. A milestone
groups by category, not by release: there is no timeline across the tracks and
none inside one, so reading them in order buys nothing. Order is decided when
work starts.

High Magic is the exception that says so out loud. It is a path rather than a
category, and a path is a sequence, so its epic
([#142](https://github.com/fancysnake/vekna/issues/142)) orders it: sub-issues
for the factory itself, blocked-by edges to the issues it waits on, and no
other issue edited to say where it sits.

- **One issue is one feature**, labelled with what it costs: `S`, `M`, `L`, or
  `Epic` for something big enough that it wants splitting into smaller
  deliverable parts before anyone starts it.
- **No versions, no schedule.** An issue says what the thing is, what it would
  ship, what is out of scope, and how you would know it worked.
- **The only reason to edit an issue is that its scope changed.** Not because
  something else shipped, not because the order moved.
- **Shipped closes the issue.** `CHANGELOG.md` is the record of what actually
  happened; a shipped plan is not kept.

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
  milestone.
- Name a track when work on it starts. The number attaches at the tag, and
  which ideas made it in is whatever the changelog says.
