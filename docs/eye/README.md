# Eye — the surfaces that watch

Ideas, not a plan. One file is one release's worth of work; nothing here says
when or in what order.

The Eye of Vecna observes (see the Hand/Eye note in
[`../reborn/common.md`](../reborn/common.md)); these are the surfaces that
*render* what the daemon and its liches are doing, as against the terminal one
the CLI already has.

Same wire, same events, another consumer — the track's rule is the consumer, not
the pixels, which is why a channel that talks back belongs here too. Mostly that
means no engine change at all; where one is here, its only payoff is the
surfaces that render it.

Shipped ones move to `../done/eye/` and stop being edited. Shared context is
[`../reborn/common.md`](../reborn/common.md).

WhatsApp notifications were **dropped, not deferred**: it cannot give a lich a
channel of its own, so it could only ever have been a notification feed with
commands routed by prefix.
