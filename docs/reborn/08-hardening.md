# Feature — 1.0 hardening

**Version:** `1.0.0`

See [00-common.md](00-common.md). Ships only once every feature above (0.1.0 –
0.7.0) is ready. 1.0 is the readiness line, not a new capability.

## Goal

The product works for the author. Make it robust, documented and **installable**
enough that a second person can use it.

## What ships

- **Published to PyPI.** `pip install vekna` gets a working tool; `vekna[discord]`
  gets the lich's channel. Release is a `mise` task, not a remembered sequence:
  build, check the wheel imports clean in a bare venv, tag, publish, verify the
  install from the index. Publishing is the first thing that makes the version
  numbers this roadmap has been spending mean anything to anyone else. The tag
  waits on `vekna.dev` being live and named in `[project.urls]`
  ([09-site.md](09-site.md)), so the published page has somewhere to point.
- **Documentation as a written thing, not a roadmap.** `README.md` around
  rituals and casts (done early, in 0.3.0, when the tmux subsystem was removed);
  a getting-started that ends in a working ritual; the lexicon's public surface
  documented per symbol; how to run a daemon and raise a lich; `docs/reborn/`
  itself moved to history, since a shipped roadmap is not a manual. This bullet
  is the inventory — [09-site.md](09-site.md) publishes it and owns nothing of
  what it says.
- Example ritual library — at least: PR triage, test-and-fix loop, migration
  babysitter. Layout follows the guidance in
  [10-ritual-modules.md](10-ritual-modules.md): split by ritual before splitting
  by kind, and let a ritual stay one file until it earns a package.
- Error pathways audited — SDK disconnects, resume on a corrupt run dir,
  malformed `rituals.py`, a `rituals/` submodule that fails to import, two
  sources declaring the same step name, a phylactery whose root no longer
  exists, Focus extra missing.
- Telemetry hooks (opt-in) for measuring primitive latency.
- Removal of any transitional shims left from earlier releases.
- `deptry`, `pip-audit`, `mypy --strict`, `vulture` all clean.

## Blast radius, and what vekna does not sandbox

Vekna does not sandbox agents, and 1.0 says so in writing rather than leaving a
second user to work it out. The agent edits your repo and runs your commands —
that is the job, and a sandbox around it would defeat the point. What the
process split buys is containment of *failure*: a broken ritual or a misbehaving
SDK kills one cast process, not the daemon and not its siblings.

Where a boundary is genuinely wanted, two things work, and neither is vekna's
to build:

- **Scope the credentials, not the process.** A ritual that triages PRs needs a
  token that can read pull requests and comment on them — not one that can push
  to `main` or read every repository in the organisation. Fine-grained GitHub
  tokens, one per ritual, least privilege. The example library ships rituals
  that state the exact permission set each one needs, because a recommendation
  nobody can act on is not a recommendation.
- **Fence the whole thing if you want a fence.** If a cast must not reach the
  host, run *vekna* inside the container — devcontainer, VM, whatever the
  project already uses — rather than expecting vekna to grow one inwards. A cast
  process is an ordinary Python process with a working directory and
  containerises like anything else, and a lich raised inside the fence keeps its
  channel, because the bot dials out.

What vekna does own stays small and stated: the daemon socket is `0600` and
user-scoped, the lich's allowlist is explicit, and `07-lich.md` carries the
warning that reaching a lich's channel means running agents in that directory on
that machine.

## Out of scope

Anything that doesn't move the product from "works for me" to "works for a
second user." New surfaces, new folios, network exposure.

**Sandboxed agent execution** — out of scope for the project, not merely for
this release. See above for the two things to do instead.

## Acceptance

- `pip install vekna` in a clean venv on a machine that has never built it, and
  the first ritual runs.
- A stranger follows the README, writes a three-step ritual, and runs it
  end-to-end from a terminal — then raises a lich and casts it from Discord.
- `mise run check`, `mise run test`, and diff-coverage pass on `main`.
