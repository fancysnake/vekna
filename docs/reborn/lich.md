# Lich — a named station that takes orders

See [common.md](common.md) — process model, wire protocol, CLI surface.

## Goal

The daemon watches; a lich works. `vekna lich` in a project directory raises a
long-lived, named station that runs one cast at a time in that directory and
takes orders from anywhere you can reach it: the terminal that raised it or
another shell. Start one before leaving the house, then watch what it is doing,
kill it, cast something else.

This is where vekna **originates** work rather than only observing it. Every
other surface observes casts and answers decides; none can start one.

## What a lich is

A named, directory-scoped station registered with the daemon. It adds the three
things the daemon lacks — identity, scope, and origination. It is not a new
engine: the daemon still owns the journal, decide routing, locks and replay.
The lich spawns `vekna cast` subprocesses, and those report themselves like any
other cast.

Three roles, still one binary:

| Role | Lifetime | Imports |
|------|----------|---------|
| cast process | one ritual, then exits | lexicon, folios, user code |
| **lich** | one directory, until dismissed | nothing of the above — it spawns, never loads |
| daemon | one per machine/user | `vekna.wire` only |

The lich sits inside the daemon's import rule, not outside it: it never loads a
`rituals.py`, so a broken ritual still kills only its own cast process. Blast
radius is unchanged.

## Phylactery

One row in the daemon's registry, kept beside `runs/`:

```text
name (key) · root · created · last cast (cast_id) · channel id
```

That is the whole of it, and it is deliberately that small. Session log and cast
history are the journal's already — "what did hollow-vesper cast" is a query
over `runs/` filtered by lich, which costs one field on the cast record and no
bookkeeping at all. A pid would restate what the lich's open socket says, only
staler.

Two of those fields are genuinely stored rather than derived:

- **Root.** A dormant lich has no connection for the daemon to learn it from,
  and raising one means spawning casts in its directory — which `--name` from
  another path, or a revive from a remote channel where there is no cwd at all,
  has no other way to know.
- **Channel id**, so a revived lich returns to its channel instead of standing
  a second one beside it.

Keyed by **name, not by directory**: a project root can hold several liches, so
the name is the only thing that identifies one. The process is not the lich;
the row is. Kill the process and the lich is dormant, not gone. A cast
interrupted by the death resumes through `vekna cast --continue`.

## Name

Generated on first rising from a themed word list, checked for collision
against every phylactery — live or dormant, since the name is the key — then
sticky. `--name` overrides. The name is the address: it titles the remote
channel, keys the daemon's routing, and is what `vekna lich attach` takes.

## Raising

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

## One cast at a time

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
daemon's lock coordination is for. `lock("project:edit")` is the tool, and this
is what makes it load-bearing rather than theoretical.

## Detached by default

`vekna lich` forks and returns; the terminal that raised it attaches as a
surface. A lich that dies with its ssh session is useless for the case it
exists for. `vekna lich attach <name>` from any other shell; detaching leaves
it running; `vekna lich dismiss <name>` ends it for good.

```toml
[lich]
detach = true
```

## Wire

A lich takes orders, so the daemon becomes a **router keyed by lich name**:

| Kind | Direction | Notes |
|------|-----------|-------|
| `LichRose` / `LichFell` | lich → daemon | name, project root, pid |
| `LichStatus` | lich → daemon | idle, or casting `<ritual>` since `<t>` + cast_id |
| `CastRequested` | surface → daemon → lich | ritual + components, or a bare prompt |
| `CastRefused` | lich → daemon → surface | busy: what runs, since when |
| `CastKillRequested` | surface → daemon → lich | |

The casts a lich spawns are ordinary casts: they attach to the daemon
themselves and emit the events they always did. The lich does not proxy the
grimoire. One field is added to `CastHello` — the lich that spawned it, absent
for a cast run by hand — and that field is what makes a lich's history a query
over the journal instead of a list something has to maintain.

`vekna --debug` is what makes this diagnosable: with routing in the middle,
"the command did nothing" has three possible homes.

## Scope

- `wire/_pacts.py` — the message kinds above.
- `pacts/lich/` — lich protocols and DTOs.
- `mills/lich/` — session state, cast slot, command dispatch, name generator
  (the word list is `specs/`).
- `mills/` + `links/` (daemon) — the phylactery registry beside `runs/`: rows
  written on rising and on each cast, read by the raising prompt, dropped by
  `dismiss`; lich registry and routing by name.
- `links/lich/spawn.py` — subprocess supervision of `vekna cast`.
- `gates/cli/click/` — `vekna lich`, `lich attach`, `lich dismiss`, `liches`.
- `inits/` — wires the lich process.

## Out of scope

Two casts in one lich. One lich over several project roots (the reverse — many
liches in one root — is supported). Anything visual — the daemon's CLI view is
the local surface.

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
  history and its interrupted cast.
- `vekna lich --name <n>` from an unrelated path raises that lich in its own
  root, not in the cwd. `dismiss` drops the row, and the next `vekna lich`
  there stops offering it.
- Two liches in one project root cast concurrently; the second blocks on
  `lock("project:edit")` while the first holds it, and the daemon shows why.
- A second `cast` while one runs is refused, naming the running ritual and its
  runtime; `kill` stops it — including while it is blocked on a decide.
- `mise run fullcheck` passes.
