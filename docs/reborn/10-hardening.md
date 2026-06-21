# Feature — 1.0 hardening

**Version:** `1.0.0`

See [00-common.md](00-common.md). Ships only once every feature above (0.1.0 –
0.9.0) is ready. 1.0 is the readiness line, not a new capability.

## Goal

The product works for the author. Make it robust and documented enough that a
second person can use it.

## What ships

- `README.md` rewritten around rituals and casts; tmux gets a section.
- Example `rituals.py` library — at least: PR triage, test-and-fix loop,
  migration babysitter.
- Error pathways audited — SDK disconnects, resume on a corrupt run dir,
  malformed `rituals.py`, Focus extra missing.
- Telemetry hooks (opt-in) for measuring primitive latency.
- Removal of any transitional shims left from earlier releases.
- `deptry`, `pip-audit`, `mypy --strict`, `vulture` all clean.

## Out of scope

Anything that doesn't move the product from "works for me" to "works for a
second user." New surfaces, new folios, network exposure.

## Acceptance

- A stranger follows the README, writes a three-rite ritual, runs it
  end-to-end from either TUI or web.
- `mise run check`, `mise run test`, and diff-coverage pass on `main`.
