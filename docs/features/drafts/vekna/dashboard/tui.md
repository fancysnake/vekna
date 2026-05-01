status: draft
updated: 2026-05-24

# Interactive dashboard for running casts

## Opening the dashboard

As a developer, I want a single command to open an interactive dashboard when I'm at a terminal, so that watching multiple casts at once isn't painful.

- the dashboard opens automatically when the command runs in an interactive terminal
- when the same command runs in a non-interactive context (pipe, cron), it prints a plain listing instead so scripts keep working

## Watching active casts

As a developer, I want a live list of currently attached casts, so that I can see what each one is doing at a glance.

- each entry shows identifier, ritual name, start time, current activity, and status
- I can drill into one cast to see its live event tree

## Watching lock state live

As a developer, I want a live list of current lock holders and waiters, so that I can see contention as it happens.

## Resolving approvals from the dashboard

As a developer, I want to see and resolve pending approvals and decisions from the dashboard, so that I don't have to switch back to each cast's terminal.

- I can see every cast currently waiting on me in one place
- resolving from the dashboard unblocks the cast immediately
- if no dashboard is attached, the cast falls back to prompting on its own terminal

## Keeping scriptable surfaces alive

As a developer, I want the daemon, cast-listing, and lock-listing commands to keep working unchanged, so that the dashboard is an addition, not a replacement.
