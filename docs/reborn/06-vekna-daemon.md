# Feature — Vekna daemon (lock coordination, journal, attach/replay)

**Version:** `0.6.0`

See [00-common.md](00-common.md) — process model, wire protocol, replay rule,
CLI surface.

## Goal

The daemon arrives. Bare `vekna` becomes the daemon: binds the user's Unix
socket, accepts cast-process connections, renders each cast's live Grimoire,
routes `decide` round-trips across the wire, coordinates locks for real, owns
the durable journal. A second `vekna` in the same account attaches as a peer
surface and sees the same view. Lock default flips to `deny`.

## What ships

- `vekna` (no subcommand) — daemon. First invocation binds
  `/tmp/vekna-<uid>.sock` (`0600`) and renders active casts to the terminal;
  later invocations attach as peer surfaces.
- Vekna-side handlers for every wire message kind.
- CLI Grimoire renderer: tree of running casts, drill-in to one, `Decide`
  prompts, response routed back to the originating cast process.
- Cross-project visibility: every cast process probing the user's socket shows
  up, regardless of `cwd`.
- **Lock manager** — project- and system-level intention-lock tree with real
  coordination. Lock state rebuilt per cast from replayed grimoire events.
  Standalone lock default flips to `deny`.
- **Durable journal** — every wire event persisted under
  `~/.config/vekna/runs/<cast_id>/` (JSONL log + `run.json`). The daemon
  already records every event for replay.
- **Resume** — `vekna casts resume <cast_id>` spawns a fresh cast process and
  hands it the journal; it replays completed rite state, re-enters the current
  rite. Always-fresh process (no pooling).
- **Attention surfacing** across casts — a cast blocked on a `decide` is
  raised to the operator wherever they are looking. The idea vekna started
  with, expressed in casts and rites rather than tmux panes.
- **Debug mode** — `vekna --debug` (and `[daemon] debug` in config) logs every
  event the daemon processes: kind, cast, direction, and what it did with it,
  including the ones it dropped or could not route. The daemon is the one place
  where every message passes, so it is the one place worth instrumenting; a
  wire protocol with no view of itself makes "the event never arrived" and "the
  handler ignored it" indistinguishable. Off by default, and never on the
  rendered view — it writes to stderr or a file, so it does not fight the
  Grimoire for the terminal.
- Clean disconnect: a cast process closing the socket marks the cast ended; an
  unclean exit surfaces as "cast disconnected", not a traceback.
- `vekna casts` (list active + recent), `vekna locks` (current locks +
  holders), `vekna unlock <key>` (admin override, confirmation).

## Scope

- `pacts/` — daemon protocols (import `vekna.wire` only; no schema mirror).
- `mills/` — daemon engine: tracks casts, multiplexes surfaces, routes
  round-trips, lock manager tree, journal writer + resume replay.
- `links/socket_server.py` — a fresh Unix-socket adapter over `vekna.wire`'s
  JSONL framing. (This once said "extend the existing tmux adapter"; that
  adapter spoke a line-based request/response protocol, not the wire's, and
  was removed with the rest of the tmux subsystem in 0.3.0.)
- `links/` filesystem journal (JSON + JSONL writer/reader).
- `gates/cli/click/` — daemon renderer + input loop; `casts`, `locks`,
  `unlock`, `casts resume`.
- `inits/` — wires the daemon.
- Lexicon wires its probe to actually attach (no behavioural change to
  standalone fallback).

## Out of scope

Originating casts — the daemon observes and coordinates; the lich casts
(0.7.0). Visual surfaces ([`../eye/`](../eye/README.md)). Cross-machine peers.
Network-exposed daemon (TCP/auth/TLS). Pooled cast processes.

## Acceptance

- Terminal A: `vekna` shows an empty view.
- Terminal B: `vekna cast fix_demo` — the cast appears in A within ~2s.
  Decides answered in A reach B.
- Terminal C: a second `vekna` attaches as a peer; same view; can answer prompts.
- Vekna killed: B keeps running standalone. Vekna restarted: B re-attaches and
  replays from `GrimoireBegin`; lock state reconstructs from the replay.
- Interrupt a cast mid-rite, `vekna casts resume <cast_id>` — picks up at that
  rite; completed rites aren't re-run; agent rites reuse the prior SDK session
  (validate with a context-dependent question across resume).
- `vekna --debug` logs every event of a full cast — hello, rites, a decide
  round-trip, goodbye — and an event addressed to a cast that has gone shows up
  as dropped rather than vanishing. Without the flag, nothing extra is printed.
- `mise run check` and `mise run test` pass.
