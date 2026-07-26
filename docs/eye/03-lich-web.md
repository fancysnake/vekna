# Feature — The lich's web surface

**Version:** Eye (`2.x`), unscheduled within it.

See [`../reborn/07-lich.md`](../reborn/07-lich.md) and [02-web.md](02-web.md).
A lich is a route on the daemon's web view, not a server of its own.

## Goal

A page per lich, shaped for a phone: what it is, what it is doing, what it did,
and a box to tell it what to do next. The same session Discord shows, rendered
instead of narrated.

## What ships

- The lich's session as a page — status, cast history, the current cast's live
  rite tree, the command box.
- The same command vocabulary as the terminal and Discord surfaces: control
  always, origination only when idle, a refusal that names what is running.
- Decides as buttons, resolving through the same path as every other surface.
- Served under the daemon's web view; `/lich/<name>`.

## The open question is auth

Discord authenticates for free — the platform knows who sent the message and
vekna checks an allowlist. A web page does not, and this is the whole reason
this feature is parked rather than scheduled: it buys a nicer view of a
capability that already arrived over Discord, at the cost of the one security
story vekna has so far avoided owning.

Two ways, to be decided when it is picked up:

1. **Bind `127.0.0.1` and let the operator bring a tunnel** — tailscale, `ssh
   -L`, cloudflared. Vekna exposes nothing and owns no auth code, and
   "network-exposed daemon" stays on the not-planned list. Recommended.
2. **Vekna grows real auth** — TLS termination, token issuance, cookie, CSRF on
   the route that starts casts, rate limiting. Reverses a resolved decision in
   [`../reborn/00-common.md`](../reborn/00-common.md); worth it only if the
   tunnel turns out to be the thing that stops you using it.

## Out of scope

Multi-user. Accounts. Reachability without a tunnel, unless the decision above
is revisited.

## Acceptance

- Open a lich's page on a phone over the tunnel: same status the Discord
  channel shows.
- Start a cast from the page; the terminal surface and the channel both see it.
- Start a second while it runs: the same refusal, in the page.
- Answer a decide from the page; the cast unblocks.
- Closing the tab kills neither the cast nor the lich.
