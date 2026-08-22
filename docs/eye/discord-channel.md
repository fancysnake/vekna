# A Discord channel per lich, and the line it pins

See [`../reborn/common.md`](../reborn/common.md) and
[`../reborn/lich.md`](../reborn/lich.md) — the station this gives a channel to,
and the command vocabulary it carries.

Start a lich before leaving the house, then from a phone watch what it is doing,
kill it, cast something else. One bot, many liches, a channel each — and a line
in each channel that says what the ritual is actually working on, which the
ritual has to publish because nothing else can know it.

The two are filed together because the pinned message is the first surface with
a **frame** to pin a line to. An append-only `vekna cast` stream has nowhere to
put one, so the status line is a stream line there and little more.

## The channel

- **`#lich-<name>` created on rising, archived on death.** Not a bot per lich —
  no platform lets you create bots programmatically. Channel-per-lich is the
  shape that costs one API call, and it carries the addressing for free: a
  message's channel says which lich it means, so no command ever needs a
  `--lich` flag.
- **Commands are plain messages** in the lich's channel, the same vocabulary as
  the terminal: control always, origination only when idle, a refusal that names
  what is running.
- **One pinned status message, edited in place**, carrying the ritual, its
  runtime, and the ritual's own status line under it. Two different sentences by
  two different authors: the lich's line says idle-or-casting, the ritual's says
  which item and which attempt. Rite deltas do not stream — Discord's rate
  limits and your notification tray both lose. `log` returns a tail on demand.
- **A decide arrives as a message with buttons** and blocks until pressed. No
  auto-approval, no timeout default: a decide is a choice the ritual author
  declared, and guessing it is worse than waiting.
- **Authorisation is an allowlist of Discord user IDs.** Anyone else is ignored
  silently.
- **An optional extra** (`vekna[discord]`). Without it a lich runs terminal-only
  and says so once, at startup.

**The daemon still binds nothing but its Unix socket.** The bot dials out over
Discord's gateway — no inbound port, no TLS, no token endpoint, no auth code of
vekna's own. "Network-exposed daemon" stays on
[`../reborn/common.md`](../reborn/common.md)'s not-planned list.

⚠️ Reaching a lich's channel means running agents in that directory on that
machine. Keep the guild private and the allowlist short.

```toml
[lich.discord]
guild    = "…"
category = "liches"      # channels are created here
allow    = ["…", "…"]    # discord user ids
# token from VEKNA_DISCORD_TOKEN
```

## The ritual's own status line

"Casting `merge_ready` for 4 minutes" is all vekna can say on its own, and it is
not enough to act on: which branch, which of eight pull requests, which attempt.
That context is the **ritual author's** — vekna cannot derive it and should not
try — so the ritual publishes it:

```python
@step
async def gates(payload: MergeReady) -> Transition:
    status(f"{payload.branch} · lint + tests")
    ...
```

- **`status(text)` in `vekna.lexicon`**, beside `emit_delta`. Free text, set
  from a step or a medium body, latest wins, `status()` clears it.
- **One grimoire event, `StatusSet(text, at)`** — cast-level, no `rite_id`,
  because it is a level and not a stream — projected onto the wire as
  `CastStatus`.
- **Every framed surface gets it for free**, from the same event: the pinned
  message here, a column in the dashboard, the TUI, the lich's page.
- **`trial.statuses`** records the texts in order, so a test can assert on them.

Why it is shaped this way:

- **Author-set, never derived.** "Current branch" is one guess of many — a
  ritual may work in a worktree, a temp clone, a pull request number, no repo at
  all. The moment vekna derives one it is wrong somewhere and needs a knob to
  say so.
- **Free text, not fields.** A `dict` of `branch`/`command`/`attempt` buys
  nothing an f-string does not and costs every surface a layout decision.
- **No medium sets it.** `shell` and `coding` already stream what they run into
  their own rite. A medium writing the status would overwrite the author's line
  every call and the author would have no way to win.

## Scope

- `links/discord/` — gateway client, channel lifecycle, pinned status, buttons.
  The only place importing the Discord client.
- `inits/` — wires the optional gateway.
- `pyproject.toml` — the `discord` extra.
- `lexicon/_mills/engine.py` — `status()`, exported from the public surface;
  `StatusSet` in `_pacts.py`; `CastStatus` in `wire/_pacts.py`, empty = cleared.
- The standalone renderer prints it as a stream line, having no frame.
- `vekna.trial` — `statuses`.

## Out of scope

A bot per lich. Multi-user: the allowlist is the model. Streaming rite output
into the channel. Progress in the status line — percentages, counters, spinners,
an ETA: a different event nobody has asked for. Markup, colour or a second line
in it; a surface that wants to truncate one line truncates it. A history of
statuses — the journal holds every `CastStatus` in order and nothing needs to
show them.

## Acceptance

- From Discord, `cast fix_demo --bound=3` starts it and the pinned status
  updates; a second `cast` is refused, naming the running ritual and its
  runtime; `kill` stops it — including while it is blocked on a decide.
- A decide reaches the channel as buttons; pressing one unblocks the cast, and
  the answer shows on the terminal surface too.
- A message from a user not on the allowlist changes nothing and gets no reply.
- Without the extra the lich runs terminal-only and says so once.
- A ritual calling `status(...)` twice leaves the second text on every surface;
  `status()` clears it; `status()` outside a cast raises, naming the call.
- `trial.statuses` holds both texts in order, and the journal carries every
  `CastStatus` the cast emitted.
- `mise run fullcheck` passes.
