# Surfaces as adapters

See [`../reborn/lich.md`](../reborn/lich.md) — the lich and its command
vocabulary — and [discord-channel.md](discord-channel.md),
the first channel.

## Goal

The lich speaks Discord. That is one platform, and the code behind it — gateway
client, channel lifecycle, a pinned status message edited in place, decides as
buttons, an allowlist — is nine parts shape to one part platform. Right now the
shape is spelled out once, inside the only implementation of it.

Pull the shape out so that a second channel is a file rather than a refactor.
Not so that vekna ships ten channels: so that the one somebody actually needs
costs an evening.

Eye is the right home for it. This is the same rule the rest of the track runs
on — same wire, same events, another consumer — applied to a consumer that
happens to talk back.

## What ships

- **`SurfaceProtocol`** in `pacts/`, stating what any remote surface owes the
  lich: deliver a command from the vocabulary in, render status out, present a
  `decide` and return an answer, and authorise a sender. That list is short
  because the lich already settled the semantics — control commands always,
  origination only when idle, a refusal that names what is running. A surface
  implements delivery; it does not get to reinterpret the rules.
- **`links/discord/` becomes the first implementation** rather than the only
  shape. No behaviour change to the lich, no new capability at this step —
  which is how it should be reviewed: if Discord's behaviour moves, the
  refactor was wrong.
- **A declared feature matrix.** A surface says what it can do — edit a message
  in place, render buttons, thread a conversation — and the lich degrades
  against what it gets: no buttons means a decide arrives as numbered options
  and a reply; no edit-in-place means status is posted on request rather than
  pinned. Degrading deliberately, not discovering at runtime that a call failed.
- **One extra per channel** (`vekna[discord]`, `vekna[telegram]`, …), and a lich
  says once at startup which surfaces it actually has — extending the notice
  the lich already gives for a missing Discord extra.
- **At least one second channel**, to prove the protocol. Which one is not the
  interesting part and is deliberately not decided here; the acceptance is that
  the second costs a file and no changes to `mills/lich/`.

## The constraint that does not move

**Every surface dials out.** The daemon binds nothing but its Unix socket, and
that stays true here — a candidate channel that needs an inbound port, a
webhook endpoint, or TLS termination of vekna's own is not a candidate. It is
the reason Discord was chosen in the first place, and it is the line that keeps
"network-exposed daemon" on [`../reborn/common.md`](../reborn/common.md)'s
not-planned list.

The lich's web page ([web-view.md](web-view.md)) is the one surface that
cannot satisfy this, which is why its auth question is settled there and not
here.

## Scope

- `pacts/surface.py` — `SurfaceProtocol`, the capability model, the command and
  decide DTOs.
- `mills/lich/` — dispatch against the protocol instead of against Discord;
  degradation rules in one place.
- `links/discord/` — reshaped to implement the protocol, unchanged in
  behaviour.
- `links/<second>/` — the proof.
- `inits/` — surfaces wired from config; unavailable extras reported once.
- `pyproject.toml` — one extra per channel.

## Out of scope

Which channels vekna chases. It does not; it makes room. Multi-user — the
allowlist per lich stays the model, and a surface that cannot identify its
sender cannot be one. Surfaces for the daemon itself: the daemon observes and
coordinates, the lich is what takes orders, and that split is the lich's,
not this doc's to revisit.

## Acceptance

- Discord behaves exactly as it did before the reshape — same pinned status, same
  buttons, same refusals, same silent ignore for a sender off the allowlist.
- A second channel is implemented in its own `links/` module with no change to
  `mills/lich/`, and carries the full vocabulary.
- A surface declaring no button support presents a decide as numbered options
  and resolves it from a reply.
- A lich configured with two surfaces accepts commands from either, and a cast
  started from one shows on both.
- A missing extra is reported once at startup, naming the surface, and the lich
  runs on what it has.
- `mise run fullcheck` passes.
