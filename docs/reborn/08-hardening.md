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
  numbers this roadmap has been spending mean anything to anyone else.
- **Documentation as a written thing, not a roadmap.** `README.md` around
  rituals and casts (done early, in 0.3.0, when the tmux subsystem was removed);
  a getting-started that ends in a working ritual; the lexicon's public surface
  documented per symbol; how to run a daemon and raise a lich; `docs/reborn/`
  itself moved to history, since a shipped roadmap is not a manual.
- Example `rituals.py` library — at least: PR triage, test-and-fix loop,
  migration babysitter.
- Error pathways audited — SDK disconnects, resume on a corrupt run dir,
  malformed `rituals.py`, a phylactery whose root no longer exists, Focus extra
  missing.
- Telemetry hooks (opt-in) for measuring primitive latency.
- Removal of any transitional shims left from earlier releases.
- `deptry`, `pip-audit`, `mypy --strict`, `vulture` all clean.

## Out of scope

Anything that doesn't move the product from "works for me" to "works for a
second user." New surfaces, new folios, network exposure.

## Acceptance

- `pip install vekna` in a clean venv on a machine that has never built it, and
  the first ritual runs.
- A stranger follows the README, writes a three-step ritual, and runs it
  end-to-end from a terminal — then raises a lich and casts it from Discord.
- `mise run check`, `mise run test`, and diff-coverage pass on `main`.
