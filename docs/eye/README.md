# Eye — `2.0.0`

The visual surfaces. Parked until [Reborn](../reborn/README.md) ships. Status
for these and every other feature is in the [roadmap](../README.md#roadmap);
what each one *is* is below.

The Eye of Vecna observes (see the Hand/Eye note in
[`../reborn/00-common.md`](../reborn/00-common.md)); these are the surfaces that
*render* what the daemon and its liches are doing, as against the terminal and
Discord surfaces that ship on the way to 1.0.

Nothing here changes the engine. Same wire, same events, another consumer —
which is why they park cleanly instead of blocking the road to 1.0.

- [01-tui.md](01-tui.md) — Textual dashboard, multi-grimoire UI.
- [02-web.md](02-web.md) — local web view, read-only then interactive.
- [03-lich-web.md](03-lich-web.md) — a page per lich, shaped for a phone.
- [04-graph.md](04-graph.md) — declared edges, then the workflow graph drawn in
  both surfaces with the walked path lit.
- [05-channels.md](05-channels.md) — the lich's Discord code reshaped into a
  surface protocol, so a second channel is a file.

The numbers 01 and 02 carried in the reborn roadmap (`0.7.0`, `0.8.0`) are
stale; these ship in the `2.x` line. The order among the five is not fixed
either.

Two of them are not visual, and belong here anyway: 04 brings a small engine
change (declared transitions) whose only payoff is the two surfaces that render
it, and 05 is another consumer of the same events — one that talks back. The
track's rule is the consumer, not the pixels.

WhatsApp notifications were **dropped, not moved**. Discord ships as the lich's
own channel at 0.7.0 and does the same job better: WhatsApp cannot give a lich
a channel of its own, so it could only ever have been a notification feed with
commands routed by prefix.
