# Feature — WhatsApp notifications and approvals

**Version:** `0.9.0`

See [00-common.md](00-common.md) and [06-vekna-daemon.md](06-vekna-daemon.md).

## Goal

Get pinged — and approve — when away from the machine.

## What ships

- Push a WhatsApp message for every `DecideRequested` event when enabled via
  config.
- Reply `yes` / `no` / `skip` in WhatsApp → `resolve()` routes the decision.
- Config in `~/.config/vekna/config.toml`: provider (Twilio / WhatsApp Cloud
  API — pick in planning), number, token from env.
- Opt-in per ritual: `@ritual(notify=["whatsapp"])` or global default.

## Scope

- `pacts/notifications.py`, `mills/notifications.py` — generic notification hook.
- `links/whatsapp/<provider>.py` — concrete adapter.
- `gates/webhook/<provider>.py` — receives inbound replies, routes to the
  decide bridge.
- Security review for webhook signature verification before merge.

## Out of scope

SMS, Slack, Discord (same pattern, separate later features).

## Acceptance

- Trigger a cast, step away, receive a WhatsApp message, reply `yes`, cast
  proceeds.
- Replies for stale casts (>5 min or after process exit) are ignored with a
  helpful message.
- Webhook signature verification passes security review.
