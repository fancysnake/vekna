# Feature — Discord: a lich's channel

**Version:** `3.0.0`

See [`../reborn/07-lich.md`](../reborn/07-lich.md) — the lich this stands a
channel in front of — and [`../reborn/00-common.md`](../reborn/00-common.md) for
the wire and the config namespace.

Filed under Reborn as the other half of `0.7.0` until the lich shipped without
it. What the lich needed from Discord was the *shape* — a station that takes
orders from a surface it does not own — and that shape is finished: the daemon
routes by lich name, a surface may speak as well as listen, and the vocabulary
is the same wherever it is typed. A channel is one more surface on that socket,
and building it is a platform integration rather than an engine change. That
makes it Hand's kind of work: acting at a distance, with an allowlist and a
token to be careful with, on an engine that is already right.

## Goal

Reach a lich from a phone. Start `merge_ready` before leaving the house, watch
what it is doing from the bus, answer the decide it stopped on, kill it and cast
something else — without a shell, a VPN, or a port open on the machine.

## What ships

One bot, many liches, a channel each. `#lich-<name>` created on rising, archived
on dismissal.

Not a bot per lich — no platform lets you create bots programmatically.
Channel-per-lich is the shape that costs one API call, and it carries the
addressing for free: a message's channel says which lich it means, so no command
ever needs a `--lich` flag.

- Commands are plain messages in the lich's channel, in the vocabulary the
  attached shell already takes: `cast <ritual> [--flag=v]`, `prompt <text>`,
  `status`, `log`, `kill`.
- **One pinned status message, edited in place**, carrying the ritual, its
  runtime, and the ritual's own `status(...)` line under it. Rite deltas do not
  stream — Discord's rate limits and your notification tray both lose. `log`
  returns a tail on demand.
- A decide arrives as a message with buttons and blocks until pressed. No
  auto-approval, no timeout default: a decide is a choice the ritual author
  declared, and guessing it is worse than waiting.
- Authorisation is an allowlist of Discord user IDs. Anyone else is ignored
  silently.

**The daemon still binds nothing but its Unix socket.** The bot dials out over
Discord's gateway — no inbound port, no TLS, no token endpoint, no auth code of
vekna's own. "Network-exposed daemon" stays on 00-common's not-planned list.

⚠️ Reaching a lich's channel means running agents in that directory on that
machine. Keep the guild private and the allowlist short.

```toml
[lich.discord]
guild    = "…"
category = "liches"      # channels are created here
allow    = ["…", "…"]    # discord user ids
# token from VEKNA_DISCORD_TOKEN
```

The Discord client is an optional extra (`vekna[discord]`). Without it a lich
runs terminal-only and says so once, at startup.

## What it needs that the lich left open

- **A channel id on the phylactery.** The row is `name · root · created · last
  cast` today; a revived lich has to return to its channel instead of standing a
  second one beside it, and that is one more stored field.
- **Answering a decide from a surface.** The lich spawns its cast with `stdin`
  on a pipe and writes nothing into it yet. A `DecideResolved` arriving from a
  surface is routed to the lich holding that cast and written down the pipe —
  the cast keeps the single blocking reader it always had, and only who is at
  the other end changes. The routing is what is missing: every other surface
  command is addressed by lich name and a decide is addressed by cast id, so the
  daemon needs the map between them.
- **Where the gateway lives.** One bot token means one gateway session, so the
  connection belongs to the **daemon** — one per user, already the router,
  already the only holder of the registry that maps a channel to a lich — rather
  than to each lich process identifying separately against a shared budget.

## Out of scope

A bot per lich. Streaming rite output into a channel. Slash commands and a
registered application command tree — a message is a message, and the vocabulary
is shared with the terminal on purpose. Any other platform: reshaping this into
an adapter behind a protocol is [`../eye/05-channels.md`](../eye/05-channels.md),
which waits on this rather than the other way round.

## Acceptance

- A lich rises: its channel appears in the configured category, with the pinned
  status message showing it idle.
- From the channel, `cast fix_demo --bound=3` starts it and the pinned status
  updates; a second `cast` is refused, naming the running ritual and its
  runtime; `kill` stops it — including while it is blocked on a decide.
- A ritual calling `status(...)` shows its line under the lich's on the pinned
  message.
- A decide reaches the channel as buttons; pressing one unblocks the cast, and
  the answer shows on an attached terminal surface too.
- A message from a user not on the allowlist changes nothing and gets no reply.
- Killing the lich process and raising it again returns it to the same channel.
- Without the `discord` extra the lich runs terminal-only and says so once.
- `mise run fullcheck` passes.
