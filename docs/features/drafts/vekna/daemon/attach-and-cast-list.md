status: draft
updated: 2026-05-24

# Daemon attach and live cast list

## Replacing the legacy tmux experience — done early, in 0.3.0

This wanted the old tmux pane-focusing commands gone in the same step the
daemon arrives. They went sooner: the whole subsystem was removed in 0.3.0
once Claude Code shipped its own notifications. `vekna tmux` no longer
resolves, and the documented commands are `cast` and `rituals`. Nothing here
is owed by 0.6.0.

## Running the daemon

As a developer, I want to start a persistent per-user daemon process, so that running casts have somewhere to register themselves.

- the daemon is one process per user on a machine
- it's reachable only by my own user account on the machine
- a bare invocation of the daemon command is reserved for the dashboard surface coming later

## Attaching a cast to the daemon automatically

As a developer, I want each cast to find and attach to the daemon if it's running, so that the daemon learns about every cast without per-call configuration.

- the cast probes for the daemon at startup and attaches when reachable
- if the daemon isn't there, the cast runs standalone as it did before
- if the daemon comes up partway through a cast, the cast attaches mid-flight on its own
- a missing daemon never produces an error — the daemon is optional infrastructure

## Listing running and recent casts

As a developer, I want to list the casts the daemon currently knows about along with recent terminated ones, so that I can see what's running and what just finished.

- live entries show identifier, ritual name, start time, and what's running right now
- recently terminated entries are kept for quick reference until the daemon is restarted
- the listing works as a scriptable command

## Isolating the daemon from cast crashes

As a developer, I want a misbehaving ritual or agent backend to be unable to take down the daemon, so that other casts keep running when one of them fails.

- each cast runs in its own process that loads user code
- the daemon never loads user code
- a crashed cast affects only itself
