status: draft
updated: 2026-05-24

# Cross-cast attention surfacing

## Ranking casts by who needs attention

As a developer, I want casts to be ranked by how urgently they need me, so that I can focus on the one that matters right now instead of polling each in turn.

- pending approvals, decisions, or questions to the operator outrank everything else
- a recent failure outranks active progress
- active progress outranks idle or lock-waiting
- terminated casts drop out of the ranking
- the ranking is recomputed continuously from each cast's recent activity

## Auto-focusing the most urgent cast

As a developer, I want the dashboard to focus the highest-ranked cast on its own, so that I don't have to hunt for it.

- the highest-ranked attached cast is highlighted by default
- its event tree is what I see first when I look in
- focus shifts on its own as ranks change

## Getting notified when a cast becomes urgent

As a developer, I want a notification when a previously quiet cast suddenly needs attention, so that I can step away from the terminal and still know to come back.

- a notification fires when a cast transitions into the "needs attention" tier
- it does not fire continuously while the cast stays in that state — once per transition only
- resolving the attention need re-arms the next transition
- I can choose between a desktop notification and a terminal bell; the bell is the default
- multiple casts transitioning at once each get their own notification

## Seeing rank in scriptable output

As a developer, I want the cast listing command to include the rank when used outside the dashboard, so that I can sort or filter from scripts.
