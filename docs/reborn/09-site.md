# Feature — the site

**Version:** `1.0.0`

See [00-common.md](00-common.md). A sibling to
[08-hardening.md](08-hardening.md) on the 1.0 readiness line, not a step after
it. 1.0 is the release that stops being for one person; a package on PyPI with
no page to send anyone to is half of that.

## Goal

Someone who hears the word "vekna" gets sent to `vekna.dev`, reads what it is
before they scroll, and can read their way from there to a ritual running on
their own machine — without cloning the repo, and without reading a roadmap.

## Where it lives

**`www/` in this repository.** Not a second repo. Documentation that sits next
to the code gets changed in the commit that changes the code; split across two
repositories, every renamed flag is two pull requests and the drift is only a
question of when. mise's own site is built from inside the mise repo, and that
is the arrangement to copy.

**Not `docs/`.** `docs/` is the plan — `reborn/`, `eye/`, `hand/`, written for
the author, in a voice that reads as intentional in a repository and as noise
on a landing page. It stays that, and does not become a build tree with a
`node_modules/` in it. The site is a separate thing with a separate audience,
and the directory split says so.

## What ships

- **Astro, with Starlight for the documentation half.** Everything under
  `/docs` is a Starlight content collection. Search is Pagefind — built at
  build time, served from the same origin, no external service. No analytics.
- **The landing page, which is this file's alone.** Hand-written at
  `www/src/pages/index.astro`, not a doc page wearing a hat: what a ritual is,
  a `rituals.py` short enough to read in one screen, the install line — the ten
  seconds that decide whether anyone reads the second page. Everything behind
  it is [08-hardening.md](08-hardening.md)'s documentation bullet, rendered:
  that file says what gets written, this one says where it is published. The
  page inventory lives there and is not restated here.
- **The blast-radius statement, reachable from the landing page.** What vekna
  does not sandbox, and the two things to do instead, are written out in
  [08-hardening.md](08-hardening.md) for the author. On the site they belong
  where a second user finds them before their first cast, not after.
- **Written fresh.** The site is not generated from `docs/reborn/` and does not
  import it — no loader, no symlink, no build step reaching into the plan. The
  one file worth recutting for the site is
  [`../architecture.md`](../architecture.md), under Contributing, for the
  reader who wants to send a patch.
- **mise runs it, like everything else.** `node` pinned in `[tools]`; tasks
  `site:dev`, `site:build`, `site:check`. `mise tasks` stays the source of
  truth and there is no second toolchain to remember.
- **CI split by path.** `ci.yml` gains `www/**` to its `paths-ignore`; a new
  `site.yml` takes `paths: ["www/**"]`. A typo fix in a doc page does not run
  the test matrix, and a change to the runtime does not rebuild the site.
- **Deployed on every push to `main`, previewed on every pull request.**
  Cloudflare Pages: the per-PR preview is what makes a documentation change
  reviewable instead of merged on faith.
- **`vekna.dev`.** The custom domain is part of the release, not a follow-up:
  registered, DNS pointed at Pages, HTTPS verified, and named in
  `[project.urls]` in `pyproject.toml` before the tag — so the PyPI page and
  the site reference each other from the first published version rather than
  being reconciled afterwards. Nothing links to a `*.pages.dev` address.
- **`site:check` guards the two things that rot fastest** — internal links, and
  the subcommands the site documents against what `vekna --help` actually
  prints. Small, and it runs in `site.yml`.

## Out of scope

- **The runtime surfaces.** Watching casts in a browser is Eye
  ([`../eye/02-web.md`](../eye/02-web.md)), and the lich's page is
  [`../eye/03-lich-web.md`](../eye/03-lich-web.md). Those are a program with a
  wire behind it; this is a static site. Sharing a domain later is fine;
  sharing a codebase now is not.
- Versioned documentation for more than the released version. One version, the
  one on PyPI, until there is a second one anybody is still running.
- A blog, a changelog page beyond linking `CHANGELOG.md`, i18n, and any design
  work past making Starlight's defaults look deliberate.

## Acceptance

The stranger who follows the README from a checkout is
[08-hardening.md](08-hardening.md)'s test. This one never touches the repo.

- A stranger arrives at `vekna.dev` knowing nothing, and reaches a running cast
  without cloning anything — the install line came off the landing page, and
  every page after it was on the site.
- The sandboxing statement is two clicks from the landing page.
- A pull request touching only `www/` builds the site, publishes a preview, and
  runs no Python job; a pull request touching only `src/` does the reverse.
- `mise run site:check` is green, and the version and extras on the site agree
  with the ones on PyPI.
