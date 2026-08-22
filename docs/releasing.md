# Releasing

What a tag does is in [`.github/workflows/release.yml`](../.github/workflows/release.yml).
This is the part no workflow can do for you.

Kept out of the site build: every step below is an account setting only the
owner can reach, which is noise on a page a stranger reads.

## One-time setup

Never done before `0.5.0`. Each of these is needed once and then never again.

### 1. PyPI trusted publisher

The project does not exist on the index yet, so this is a **pending** publisher
rather than a setting on an existing project.

- [ ] [pypi.org](https://pypi.org) → *Your account* → *Publishing* → *Add a
      pending publisher* (GitHub tab)

  | field | value |
  |-------|-------|
  | PyPI project name | `vekna` |
  | Owner | `fancysnake` |
  | Repository name | `vekna` |
  | Workflow name | `release.yml` |
  | Environment name | `pypi` |

The environment name is not optional here — the workflow declares
`environment: pypi`, and a publisher registered without it will refuse the
upload.

### 2. TestPyPI trusted publisher

Same form, different site and environment. This is what makes a rehearsal
possible, and a rehearsal is what stops a rejected classifier from burning a
version number that can never be reused.

- [ ] [test.pypi.org](https://test.pypi.org) → *Your account* → *Publishing* →
      *Add a pending publisher*, identical to the table above except:

  | field | value |
  |-------|-------|
  | Environment name | `testpypi` |

### 3. GitHub environments

- [ ] *Settings* → *Environments* → *New environment* → `pypi`
- [ ] *Settings* → *Environments* → *New environment* → `testpypi`

No secrets go in either. They exist so the OIDC token the workflow mints is
scoped to something, and so a required reviewer can be added later without
touching the workflow.

### 4. GitHub Pages

- [ ] *Settings* → *Pages* → *Build and deployment* → Source: **GitHub Actions**

Not "Deploy from a branch". The site is built by
[`site.yml`](../.github/workflows/site.yml) and uploaded as an artifact; there
is no `gh-pages` branch and nothing to point a branch source at.

### 5. DNS

- [ ] In the `fancysnake.dev` zone, add `CNAME  vekna  →  fancysnake.github.io`
- [ ] After the first deploy: *Settings* → *Pages* → *Custom domain* →
      `vekna.fancysnake.dev`, wait for the DNS check to pass
- [ ] Tick **Enforce HTTPS** once the certificate is issued (minutes, sometimes
      an hour)

`docs/CNAME` is in the build already, so the domain survives every redeploy. The
repository setting still has to be told once.

## Every release

- [ ] Branch off `main`. Never commit the release directly to it.
- [ ] Bump `version` in `pyproject.toml`
- [ ] `CHANGELOG.md`: rename `## [Unreleased] - ???` to the version and today's
      date, and open a fresh `Unreleased` above it
- [ ] `mise run fullcheck` — green, no exceptions
- [ ] `mise run site:check` — green
- [ ] `mise run release:build` — builds both artifacts and installs each into a
      venv that has never seen this project
- [ ] Open the pull request, and let CI agree with what you ran locally
- [ ] Optional rehearsal: *Actions* → *Release* → *Run workflow*. Builds and
      publishes to TestPyPI only — no tag spent, and whatever only an index can
      reject shows up here
- [ ] Merge to `main`
- [ ] Tag on `main` and push it:

      ```bash
      git checkout main && git pull
      git tag v0.5.0
      git push origin v0.5.0
      ```

      The workflow refuses to publish a wheel whose version is not the tag, so a
      forgotten bump fails in the first job rather than on the index.

- [ ] Watch the run: `build → testpypi → publish → verify → github-release`.
      `verify` installs from PyPI and imports it, so a green run means the index
      serves something that works, not merely that an upload succeeded.

## After the first release

- [ ] [pypi.org/project/vekna](https://pypi.org/project/vekna/) exists, and
      *Manage* → *Publishing* shows the publisher against the project rather
      than in the pending list. The first upload is what creates the project and
      converts the pending publisher; until then the name is claimed by nobody.
- [ ] The PyPI page renders the README, and the sidebar links resolve
- [ ] `pip install vekna` in a fresh venv on a machine that has never built it,
      and the first ritual runs — the one acceptance a workflow cannot check
      for you
