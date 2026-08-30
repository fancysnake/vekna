# Eye — the surfaces that watch

Ideas, not a plan. They live as GitHub issues under the
[Eye milestone](https://github.com/fancysnake/vekna/milestone/2), sized `S` /
`M` / `L` / `Epic`; nothing there says when or in what order.

The Eye of Vecna observes (see the Hand/Eye note in
[`../reborn/common.md`](../reborn/common.md)); these are the surfaces that
*render* what the daemon and its liches are doing, as against the terminal one
the CLI already has.

Same wire, same events, another consumer — the track's rule is the consumer, not
the pixels, which is why a channel that talks back belongs here too. Mostly that
means no engine change at all; where one is here, its only payoff is the
surfaces that render it.

Shipped ones close and land in `CHANGELOG.md`. Shared context is
[`../reborn/common.md`](../reborn/common.md).

WhatsApp notifications were **dropped, not deferred**: it cannot give a lich a
channel of its own, so it could only ever have been a notification feed with
commands routed by prefix.
