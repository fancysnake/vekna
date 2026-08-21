# Feature — Lich (a named station, remote-controlled)

**Version:** `0.8.0` — **in progress.**

See [00-common.md](00-common.md) — process model, wire protocol, CLI surface —
and [06-vekna-daemon.md](06-vekna-daemon.md), which this builds on.

## Goal

The daemon watches; a lich works. `vekna lich` in a project directory raises a
long-lived, named station that runs one cast at a time in that directory and
takes orders from anywhere you can reach it: the terminal that raised it,
another shell, or a Discord channel of its own. Start one before leaving the
house, then from a phone watch what it is doing, kill it, cast something else.

This is the first release where vekna **originates** work remotely. Every
surface up to here observes casts and answers decides; none can start one.

## What a lich is

A named, directory-scoped station registered with the daemon. It adds the three
things the daemon lacks — identity, scope, and origination. It is not a new
engine: the daemon still owns the journal, decide routing, locks and replay.
The lich spawns `vekna cast` subprocesses, and those report themselves like any
other cast.

Three roles now, still one binary:

| Role | Lifetime | Imports |
|------|----------|---------|
| cast process | one ritual, then exits | lexicon, folios, user code |
| **lich** | one directory, until dismissed | nothing of the above — it spawns, never loads |
| daemon | one per machine/user | `vekna.wire` only |

The lich sits inside the daemon's import rule, not outside it: it never loads a
`rituals.py`, so a broken ritual still kills only its own cast process. Blast
radius is unchanged.

### Phylactery

One row in the daemon's registry, kept beside `runs/`:

```text
name (key) · root · created · last cast (cast_id) · discord channel id
```

That is the whole of it, and it is deliberately that small. Session log and cast
history are the journal's already — "what did hollow-vesper cast" is a query
over `runs/` filtered by lich, which costs one field on the cast record and no
bookkeeping at all. A pid would restate what the lich's open socket says, only
staler.

Two of those fields are genuinely stored rather than derived:

- **Root.** A dormant lich has no connection for the daemon to learn it from,
  and raising one means spawning casts in its directory — which `--name` from
  another path, or a revive from Discord where there is no cwd at all, has no
  other way to know.
- **Channel id**, so a revived lich returns to its channel instead of standing
  a second one beside it.

Keyed by **name, not by directory**: a project root can hold several liches, so
the name is the only thing that identifies one. The process is not the lich;
the row is. Kill the process and the lich is dormant, not gone. A cast
interrupted by the death resumes through the daemon's `vekna cast --continue`.

### Name

Generated on first rising from a themed word list, checked for collision
against every phylactery — live or dormant, since the name is the key — then
sticky. `--name` overrides. The name is the address: it titles the Discord
channel, keys the daemon's routing, and is what `vekna lich attach` takes.

### Raising

Where nothing sleeps, `vekna lich` raises a new lich and names it. Otherwise
vekna cannot know which one you meant, and guessing is wrong in both directions
— silently reviving a lich you had finished with is no better than silently
abandoning one you meant to continue. So it asks, listing what sleeps there and
what each last did:

```text
Two liches sleep here.
  [1] hollow-vesper   last cast fix_demo, 3 days ago
  [2] ashen-quill     last cast pr_triage, yesterday
  [n] a new one
```

**The list is filtered by root** — the rows whose directory is this one, not
every lich you have ever raised. Without that the prompt is fifty entries deep
by the second month and the feature is worse than no feature.

Flags skip the prompt: `--name <n>` raises that one, dormant or new; `--new`
always raises a fresh one. So scripts and `mise` tasks never sit on a question.

`vekna lich attach` with no name asks the same way against the *live* liches
rooted here — one, attach to it; several, ask; none, say so.

Rows accumulate. `vekna lich dismiss <name>` is the deliberate way out: it ends
the lich, archives its channel, and drops the row. Whether rows should also age
out on their own is **open** — a lich raised once, which cast nothing and has
not been touched in a month, is noise in every prompt it appears in, but a
reaper needs a rule and the rule needs a number that only use will supply.

### One cast at a time

A lich runs one cast, never two. A second `cast` while busy is **refused, not
queued** — and the refusal names the running ritual, how long it has run, and
that `kill` is the way out. Nothing queued means no backlog to reason about and
nothing silently lost when the process dies.

Commands split accordingly:

| Kind | When | Commands |
|------|------|----------|
| **Control** | always | `status`, `log`, `rituals`, `kill`, decide answers |
| **Origination** | idle only | `cast <ritual> [--flag=v]`, `prompt <text>` |

Control must work while a cast runs *and* while that cast sits blocked on a
decide. Otherwise the one command worth having from a phone is the one you
cannot issue. So the lich supervises its subprocess and serves its surfaces as
separate tasks, with the cast slot as shared state — never a lock the command
loop waits on.

This is the **lich's** rule, not the directory's. Several liches can stand in
one project root and cast at the same time; the slot buys serial work per
station, and keeping two stations out of each other's files is what the
daemon's lock coordination (0.7.0) is for. `lock("project:edit")` is the tool,
and this is the release that makes it load-bearing rather than theoretical.

### The status line

"Casting `merge_ready` for 4 minutes" is all the lich can say on its own, and
it is not enough to act on: which branch, which of eight PRs, which attempt.
That context is the **ritual author's** — vekna cannot derive it and should not
try — so the ritual publishes it and every framed surface shows it:

```python
@step
async def gates(payload: MergeReady) -> Transition:
    status(f"{payload.branch} · lint + tests")
    ...
```

- **`status(text)` in `vekna.lexicon`**, beside `emit_delta`. Free text, set
  from a step or a medium body, latest wins, `status()` clears it. One grimoire
  event, `StatusSet(text, at)`, cast-level — no `rite_id`, because it is a
  level and not a stream — projected onto the wire as `CastStatus`.
- **`LichStatus` says idle-or-casting; this is the ritual's own words.** Two
  different sentences by two different authors, and the pinned message carries
  both: the lich's line, then the ritual's under it.
- **Author-set, never derived.** "Current branch" is one guess of many — a
  ritual may work in a worktree, a temp clone, a PR number, no repo at all. The
  moment vekna derives one it is wrong somewhere and needs a knob to say so.
- **Free text, not fields.** A `dict` of `branch`/`command`/`attempt` buys
  nothing an f-string does not and costs every surface a layout decision.
- **No medium sets it.** `shell` and `coding` already stream what they run into
  their own rite. A medium writing the status would overwrite the author's line
  every call and the author would have no way to win.

It ships here because here is the first surface with a **frame** to pin a line
to — `vekna cast` is an append-only stream, where a status is just another
line. The dashboard gains a column for it retroactively, from the same
event, and Eye's TUI and the lich's web page get it for free
([`../eye/`](../eye/README.md)).

### Detached by default

`vekna lich` forks and returns; the terminal that raised it attaches as a
surface. A lich that dies with its ssh session is useless for the case it
exists for. `vekna lich attach <name>` from any other shell; detaching leaves
it running; `vekna lich dismiss <name>` ends it for good.

## Discord

One bot, many liches, a channel each. `#lich-<name>` created on rising, archived
on death.

Not a bot per lich — no platform lets you create bots programmatically.
Channel-per-lich is the shape that costs one API call, and it carries the
addressing for free: a message's channel says which lich it means, so no
command ever needs a `--lich` flag.

- Commands are plain messages in the lich's channel.
- **One pinned status message, edited in place**, carrying the ritual, its
  runtime, and the ritual's own status line under it. Rite deltas do not
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
[lich]
detach = true

[lich.discord]
guild    = "…"
category = "liches"      # channels are created here
allow    = ["…", "…"]    # discord user ids
# token from VEKNA_DISCORD_TOKEN
```

The Discord client is an optional extra (`vekna[discord]`). Without it a lich
runs terminal-only and says so once, at startup.

## Wire

Until now the wire flows one way plus decide round-trips: casts report,
surfaces answer. A lich takes orders, so the daemon becomes a **router keyed by
lich name**. New kinds:

| Kind | Direction | Notes |
|------|-----------|-------|
| `LichRose` / `LichFell` | lich → daemon | name, project root, pid |
| `LichStatus` | lich → daemon | idle, or casting `<ritual>` since `<t>` + cast_id |
| `CastRequested` | surface → daemon → lich | ritual + components, or a bare prompt |
| `CastRefused` | lich → daemon → surface | busy: what runs, since when |
| `CastKillRequested` | surface → daemon → lich | |
| `CastStatus` | cast → daemon → surface | the ritual's own line; empty = cleared |

The casts a lich spawns are ordinary casts: they attach to the daemon
themselves and emit the events they always did. The lich does not proxy the
grimoire. One field is added to `CastHello` — the lich that spawned it, absent
for a cast run by hand — and that field is what makes a lich's history a query
over the journal instead of a list something has to maintain.

## Debug

The daemon's `--debug` (see 06) is what makes this release diagnosable — with
routing in the middle, "the button did nothing" has three possible homes.

## Scope

- `wire/_pacts.py` — the message kinds above.
- `lexicon/` — `status()` in `_mills/engine.py` and exported; `StatusSet` in
  `_pacts.py`; the standalone renderer prints it as a stream line, having no
  frame to pin it to; `trial.statuses` records it.
- `pacts/lich.py` — the phylactery row, the registry protocol the mills hold,
  the station protocol a session view paints, and the lich's errors.
- `mills/station.py` — session state, cast slot, command dispatch.
- `mills/liches.py` — the daemon's half: the phylactery registry beside `runs/`
  (rows written on rising and on each cast, read by the raising prompt, dropped
  by `dismiss`), routing by name, and the name generator (the word list is
  `specs/names.py`).
- `links/registry.py` — the registry file.
- `links/spawn.py` — subprocess supervision of `vekna cast`.
- `links/discord/` — gateway client, channel lifecycle, pinned status, buttons.
  Optional extra; the only place importing the Discord client.
- `gates/cli/lich.py` — the raising prompt and the session view.
- `inits/cli.py` — `vekna lich`, `lich attach`, `lich dismiss`, `liches`; wires
  the lich process and the optional gateway.

## Out of scope

Progress in the status line — percentages, counters, spinners, an ETA: a
different event nobody has asked for. Markup, colour or a second line in it; a
surface that wants to truncate one line truncates it. A history of statuses —
the journal holds every `CastStatus` in order and nothing needs to show them.
Two casts in one lich. One lich over several project roots (the reverse — many
liches in one root — is supported). A web surface for the lich
([`../eye/`](../eye/README.md)). Anything visual — the daemon's CLI view is the
local surface at this release.

## Acceptance

- `vekna lich` in a project returns to the prompt; `vekna liches` lists it,
  named and idle.
- `vekna lich attach <name>` from a second shell shows the same session; a cast
  started from either shell is visible in both.
- Close every shell: the lich still runs and `attach` finds it. Kill the
  process, then `vekna lich` in the same directory: with one lich sleeping
  there it offers that name or a new one; with two it lists both and what each
  last did; a lich rooted in a *different* directory is not offered at all;
  `--name` and `--new` answer without asking. Reviving one brings back its
  history, its channel, and its interrupted cast.
- `vekna lich --name <n>` from an unrelated path raises that lich in its own
  root, not in the cwd. `dismiss` drops the row, and the next `vekna lich`
  there stops offering it.
- Two liches in one project root cast concurrently; the second blocks on
  `lock("project:edit")` while the first holds it, and the daemon shows why.
- From Discord, `cast fix_demo --bound=3` starts it and the pinned status
  updates; a second `cast` is refused, naming the running ritual and its
  runtime; `kill` stops it — including while it is blocked on a decide.
- A ritual calling `status(...)` twice leaves the second text on the pinned
  message and on `status`; `status()` clears it; `status()` outside a cast
  raises, naming the call. `trial.statuses` holds both texts in order.
- A decide reaches the channel as buttons; pressing one unblocks the cast, and
  the answer shows on the terminal surface too.
- A message from a user not on the allowlist changes nothing and gets no reply.
- Without the `discord` extra the lich runs terminal-only and says so once.
- `mise run fullcheck` passes.
