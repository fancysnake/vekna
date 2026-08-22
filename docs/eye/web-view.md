# The web view, and the lich's page on it

See [`../reborn/common.md`](../reborn/common.md). Same events, different
surface. Another bus consumer — no engine changes.

One server, two audiences: a page for the casts running on this machine, and a
route per lich shaped for a phone. The second is why the auth question in here
is a real question rather than "bind loopback and stop".

## The web view

A local web page showing the active casts, streaming rite output, and (second
cut) fielding decides.

- `vekna web` serves a single-page app on `127.0.0.1:PORT` subscribing to the
  bus over WebSocket.
- Read-only first: cast tree, rite streams, decide requests visible but not
  actionable.
- Second cut: decide buttons wired to the same `resolve()` mechanism as
  CLI/TUI.
- Auth: localhost-only. Anything reachable beyond loopback is **unresolved** —
  see below — so `0.0.0.0` does not ship until it is settled. Not a URL token: a
  token in the URL leaks through browser history, server logs, copied links and
  referrers, so whatever the answer turns out to be, it carries in a header or a
  cookie.

Scope: `gates/web/<framework>/app.py` (FastAPI or aiohttp — pick during
planning); a static SPA bundle, minimal (prefer HTMX/Alpine over a build
toolchain; inline a tiny React only if genuinely needed);
`links/web/broadcast.py` for WebSocket fan-out. No engine changes.

## The lich's page

A page per lich, shaped for a phone: what it is, what it is doing, what it did,
and a box to tell it what to do next. The same session a chat channel shows,
rendered instead of narrated. A lich is a route on this server, `/lich/<name>`,
not a server of its own.

- The lich's session as a page — status, cast history, the current cast's live
  rite tree, the command box.
- The same command vocabulary as the terminal and chat surfaces: control always,
  origination only when idle, a refusal that names what is running.
- Decides as buttons, resolving through the same path as every other surface.

## The open question is auth

A chat platform authenticates for free — it knows who sent the message and vekna
checks an allowlist. A web page does not, and this is the awkward part: the lich
page buys a nicer view of a capability a chat channel already carries, at the
cost of the one security story vekna has so far avoided owning.

Two ways, to be decided when it is picked up:

1. **Bind `127.0.0.1` and let the operator bring a tunnel** — tailscale, `ssh
   -L`, cloudflared. Vekna exposes nothing and owns no auth code, and
   "network-exposed daemon" stays on the not-planned list. Recommended.
2. **Vekna grows real auth** — TLS termination, token issuance, cookie, CSRF on
   the route that starts casts, rate limiting. Reverses a resolved decision in
   [`../reborn/common.md`](../reborn/common.md); worth it only if the tunnel
   turns out to be the thing that stops you using it.

## Out of scope

Multi-user. Accounts. History-browsing UI (the journal is on disk; add a history
page later if asked). Reachability without a tunnel, unless the decision above
is revisited.

## Acceptance

- Start a cast, open the web view, see the same state the TUI shows; answer a
  decide from the browser and the cast unblocks; closing the tab kills neither
  the cast nor the lich.
- Open a lich's page on a phone over the tunnel: the same status its chat
  channel shows.
- Start a cast from the page and the terminal surface and the channel both see
  it; start a second while it runs and the same refusal appears in the page.
- `mise run fullcheck` passes.
