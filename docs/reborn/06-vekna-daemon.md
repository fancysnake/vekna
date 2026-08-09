# Feature — Vekna daemon (journal, attach/replay, resume)

**Version:** `0.6.0` — **in progress.**

See [00-common.md](00-common.md) — process model, wire protocol, replay rule,
CLI surface.

## Goal

The daemon arrives. Bare `vekna` becomes the daemon: binds the user's Unix
socket, accepts cast-process connections, renders each cast's live Grimoire,
raises the ones waiting on a human, owns the durable journal. A second `vekna`
in the same account attaches as a peer surface and sees the same view.

It observes. A cast answers its prompts on the stdin of the terminal that
started it, attached or not; what the wire carries is that the cast is
*waiting*, so the operator can be told from anywhere. Coordination — locks —
lands on top of this at [0.7.0](05-locks.md).

## What ships

- `vekna` (no subcommand) — daemon. First invocation binds
  `/tmp/vekna-<uid>.sock` (`0600`) and renders active casts to the terminal;
  later invocations attach as peer surfaces.
- Vekna-side handlers for every wire message kind.
- CLI Grimoire renderer: tree of running casts, drill-in to one, and a cast
  blocked on a prompt marked as waiting — with the prompt, and where to answer
  it. The mark clears on `DecideResolved`.
- Cross-project visibility: every cast process probing the user's socket shows
  up, regardless of `cwd`.
- **Durable journal** — every wire event persisted under
  `~/.config/vekna/runs/<cast_id>/` (JSONL log + `run.json`). The daemon
  already records every event for replay. A standalone cast writes none: the
  durable half is the daemon's, and a second writer would be a second format to
  keep right.
- **Resume** — `vekna casts resume <cast_id>` spawns a fresh cast process and
  hands it the journal; it replays completed rite state, re-enters the current
  rite. Always-fresh process (no pooling). Medium rites come back from the
  journal, so no agent is called twice; step rites re-run, a `Transition` being
  a function reference no journal can hold.
- **Attention surfacing** across casts — a cast blocked on a `decide` is
  raised to the operator wherever they are looking. The idea vekna started
  with, expressed in casts and rites rather than tmux panes.
- **Debug mode** — `vekna --debug` logs every event the daemon processes: kind,
  cast, direction, and what it did with it, including the ones it dropped or
  could not route. The daemon is the one place where every message passes, so
  it is the one place worth instrumenting; a wire protocol with no view of
  itself makes "the event never arrived" and "the handler ignored it"
  indistinguishable. Off by default, and never on the rendered view — it writes
  to a file, whose path is echoed once at startup, so it does not fight the
  Grimoire for the terminal.
- Clean disconnect: a cast process closing the socket marks the cast ended; an
  unclean exit surfaces as "cast disconnected", not a traceback.
- `vekna casts` (list active + recent).

## Scope

- `pacts/` — daemon protocols (import `vekna.wire` only; no schema mirror).
- `mills/` — daemon engine: tracks casts, multiplexes surfaces, holds the open
  prompts, journal writer + resume replay.
- `links/socket_server.py` — a fresh Unix-socket adapter over `vekna.wire`'s
  JSONL framing. (This once said "extend the existing tmux adapter"; that
  adapter spoke a line-based request/response protocol, not the wire's, and
  was removed with the rest of the tmux subsystem in 0.3.0.)
- `links/` filesystem journal (JSON + JSONL writer/reader).
- `gates/cli/click/` — daemon renderer + input loop; `casts`, `casts resume`.
- `inits/` — wires the daemon.
- Lexicon wires its probe to actually attach: a send-only wire client, and a
  `Channel` that tees the prompt it is opening onto the wire and the answer
  after it. No behavioural change to the standalone path — it *is* the
  standalone path, with a listener added.

## Out of scope

**Locks** — the whole lock manager, `vekna locks`, `vekna unlock`, and lock
state rebuilt from replay ([05-locks.md](05-locks.md), 0.7.0). **Takeover** —
answering a blocked cast from `vekna`. It is one message and the hub already
holds the state it would answer into; what it costs is on the cast side, where
the local read is a thread that cannot be cancelled, so the loser would stay
blocked and eat the next line typed into that terminal. Racing the two wants
stdin read through `loop.add_reader`. Deferred rather than dropped — and at
0.8.0 the question changes shape anyway, a lich holding the stdin of the casts
it spawns. Originating casts — the daemon observes; the lich casts (0.8.0).
Visual surfaces ([`../eye/`](../eye/README.md)). Cross-machine peers.
Network-exposed daemon (TCP/auth/TLS). Pooled cast processes.

## Acceptance

- Terminal A: `vekna` shows an empty view.
- Terminal B: `vekna cast fix_demo` — the cast appears in A within ~2s.
- A `decide` in B is answered in B. A shows it waiting while it is open, with
  the prompt, and stops showing it once answered.
- Terminal C: a second `vekna` attaches as a peer; same view, including what is
  waiting.
- Vekna killed: B keeps running standalone, prompts included. Vekna restarted:
  B re-attaches and replays from `GrimoireBegin`.
- Interrupt a cast mid-rite, `vekna casts resume <cast_id>` — picks up at that
  rite; completed rites aren't re-run; agent rites reuse the prior SDK session
  (validate with a context-dependent question across resume).
- `vekna --debug` logs every event of a full cast — hello, rites, a decide
  announced and resolved, goodbye — and an event addressed to a cast that has
  gone shows up as dropped rather than vanishing. Without the flag, nothing
  extra is printed.
- `mise run fullcheck` passes.
