# Feature — the site

**Version:** `0.5.0` — **in progress.**

> Filed at `1.0.0` and pulled forward: vekna is in use outside this repository
> before the daemon or the lich exist, and a checkout is no way to install it.
> What moved with it is [08-hardening.md](08-hardening.md)'s publishing bullet —
> a package on PyPI with no page to send anyone to is half a release. Three
> decisions changed on the way, and each is a simplification: mkdocs-material
> rather than Astro and Starlight, GitHub Pages rather than Cloudflare,
> `vekna.fancysnake.dev` rather than a domain of its own. The hand-written
> landing page is dropped — this is a documentation site, and a home page is
> worth writing when there is an audience to write it for.

See [00-common.md](00-common.md). A sibling to
[08-hardening.md](08-hardening.md)'s publishing half, not a step after it: a
package nobody can read about is half of being installable.

## Goal

Someone who hears the word "vekna" gets sent to `vekna.fancysnake.dev`, reads
what it is before they scroll, and can read their way from there to a ritual
running on their own machine — without cloning the repo, and without reading a
roadmap.

## Where it lives

**`mkdocs.yml` at the repository root, `docs_dir` at its default.**
Documentation that sits next to the code gets changed in the commit that
changes the code; split across two repositories, every renamed flag is two pull
requests and the drift is only a question of when.

**In `docs/`, beside the plan.** This file argued for a separate tree — `www/`
— on the grounds that `reborn/`, `eye/` and `hand/` are written for the author
and read as noise to anyone arriving from PyPI. That reasoning holds; the
directory split was not the only way to buy it. mkdocs' own `exclude_docs`
keeps the plan out of the build in four lines, and one directory means one
place to look rather than two conventions for where a `.md` goes.

## What ships

- **mkdocs, with the Material theme.** Search is Material's own, built at build
  time and served from the same origin. No external service, no analytics, and
  no second toolchain — it installs from `pyproject.toml`'s `docs` group like
  everything else the project runs.
- **Eight pages, and no landing page.** `index.md` is documentation rather than
  a pitch: what a ritual is, the install line, and a first ritual running. Then
  rituals, mediums, testing, examples, safety, the CLI reference, and
  `architecture.md` published where it already sits. A hand-written home page
  is worth building when there is an audience to build it for.
- **The blast-radius statement as a page of its own.** What vekna does not
  sandbox, and the two things to do instead, are written out in
  [08-hardening.md](08-hardening.md) for the author. On the site they are one
  click from the front page, because a second user should meet them before
  their first cast rather than after.
- **Written fresh.** The site is not generated from `docs/reborn/` and does not
  import it — no loader, no symlink, no build step reaching into the plan.
- **mise runs it, like everything else.** Tasks `site:dev`, `site:build`,
  `site:check`. `mise tasks` stays the source of truth.
- **CI split by path.** `ci.yml` already ignored `docs/**` and gains
  `mkdocs.yml`; a new `site.yml` takes exactly those paths. A typo fix in a doc
  page does not run the test matrix, and a change to the runtime does not
  rebuild the site.
- **Deployed on every push to `main`.** GitHub Pages, from the workflow. A pull
  request builds and stops there: Pages has no per-branch preview, and the
  strict build failing is most of what a preview would have caught.
- **`vekna.fancysnake.dev`.** A subdomain of a domain that already exists
  rather than a registration of its own. Named in `[project.urls]` before the
  tag, so the PyPI page and the site reference each other from the first
  published version rather than being reconciled afterwards.
- **The two things that rot fastest are guarded.** Internal links, by
  `mkdocs build --strict`, which is what `site:check` is. And the commands the
  CLI page documents against what click actually registers — that one is a test
  in the suite rather than part of `site:check`, because it breaks on a Python
  change and the suite is what runs on those.

## Out of scope

- **The runtime surfaces.** Watching casts in a browser is Eye
  ([`../eye/02-web.md`](../eye/02-web.md)), and the lich's page is
  [`../eye/03-lich-web.md`](../eye/03-lich-web.md). Those are a program with a
  wire behind it; this is a static site. Sharing a domain later is fine;
  sharing a codebase now is not.
- Versioned documentation for more than the released version. One version, the
  one on PyPI, until there is a second one anybody is still running.
- A blog, a changelog page beyond linking `CHANGELOG.md`, i18n, and any design
  work past making the theme's defaults look deliberate.

## Acceptance

The stranger who follows the README from a checkout is
[08-hardening.md](08-hardening.md)'s test. This one never touches the repo.

- A stranger arrives at `vekna.fancysnake.dev` knowing nothing, and reaches a
  running cast without cloning anything — the install line came off the first
  page, and every page after it was on the site.
- The sandboxing statement is one click from the front page.
- A pull request touching only `docs/` builds the site and runs no Python job;
  a pull request touching only `src/` does the reverse.
- `mise run site:check` is green, and the version and extras on the site agree
  with the ones on PyPI.
