# Feature — Web view

**Version:** `0.8.0`

See [00-common.md](00-common.md) and [06-vekna-daemon.md](06-vekna-daemon.md).
Same events, different surface. Another bus consumer — no engine changes.

## Goal

A local web page showing the active casts, streaming rite output, and (second
cut) fielding approvals.

## What ships

- `vekna web` serves a single-page app on `127.0.0.1:PORT` subscribing to the
  bus over WebSocket.
- Read-only first: cast tree, rite streams, approval requests visible but not
  actionable.
- Second cut, same release: approval buttons wired to the same `resolve()`
  mechanism as CLI/TUI.
- Auth: localhost-only; short-lived token in the URL for `0.0.0.0` use (off by
  default).

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
- Approve from the browser; the cast unblocks.
- Closing the tab doesn't kill the cast.
