# Eye — the visual surfaces

Parked after 1.0. The Eye of Vecna observes (see the Hand/Eye note in
[`../reborn/00-common.md`](../reborn/00-common.md)); these are the surfaces
that *render* what the daemon and its liches are doing, as against the terminal
and Discord surfaces that ship on the way to 1.0.

Nothing here changes the engine. Same wire, same events, another consumer —
which is why they park cleanly instead of blocking the road to 1.0.

- [01-tui.md](01-tui.md) — Textual dashboard, multi-grimoire UI.
- [02-web.md](02-web.md) — local web view, read-only then interactive.
- [03-lich-web.md](03-lich-web.md) — a page per lich, shaped for a phone.

The versions in 01 and 02 are the numbers they carried while they sat in the
reborn roadmap; treat them as stale. The order among the three is not fixed
either.

WhatsApp notifications were **dropped, not moved**. Discord ships as the lich's
own channel at 0.7.0 and does the same job better: WhatsApp cannot give a lich
a channel of its own, so it could only ever have been a notification feed with
commands routed by prefix.
