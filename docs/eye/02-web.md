# Feature — Web view

**Version:** Eye (`2.x`), unscheduled within it. (Held a reborn slot once.)

See [`../reborn/00-common.md`](../reborn/00-common.md) and
[`../reborn/06-vekna-daemon.md`](../reborn/06-vekna-daemon.md). Same events,
different surface. Another bus consumer — no engine changes. The per-lich page
is [03-lich-web.md](03-lich-web.md), which owns the auth question — still open
there, since that is the surface that would need it.

## Goal

A local web page showing the active casts, streaming rite output, and (second
cut) fielding decides.

## What ships

- `vekna web` serves a single-page app on `127.0.0.1:PORT` subscribing to the
  bus over WebSocket.
- Read-only first: cast tree, rite streams, decide requests visible but not
  actionable.
- Second cut, same release: decide buttons wired to the same `resolve()`
  mechanism as CLI/TUI.
- Auth: localhost-only, and that is the whole story here. Anything reachable
  beyond loopback is **unresolved** — see below — so `0.0.0.0` does not ship
  until it is settled. Not a URL token: a token in the URL leaks through
  browser history, server logs, copied links and referrers, so whatever the
  answer turns out to be, it carries in a header or a cookie.

## Scope

- `gates/web/<framework>/app.py` (FastAPI or aiohttp — pick during planning).
- Static SPA bundle, minimal (prefer HTMX/Alpine over a build toolchain; inline
  a tiny React only if genuinely needed).
- `links/web/broadcast.py` — WebSocket fan-out.
- No engine changes.

## Out of scope

Multi-user. Remote access. History-browsing UI (data is on disk from 0.6.0;
add a history page later if asked).

## Acceptance

- Start a cast, open the web view, see the same state the TUI shows.
- Answer a decide from the browser; the cast unblocks.
- Closing the tab doesn't kill the cast.
