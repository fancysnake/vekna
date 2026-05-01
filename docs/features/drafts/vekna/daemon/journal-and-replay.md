status: draft
updated: 2026-05-24

# Durable cast history and replay on attach

## Persisting every event

As a developer, I want the daemon to write every received event to disk per cast, so that I can review what happened even after the daemon or cast is gone.

- events for a cast are saved in arrival order, one record at a time
- nothing in the history is rewritten after the fact

## Replaying a cast on every attach

As a developer, I want each cast to replay its complete event history when it attaches, so that the daemon's view of the cast is authoritative even after restarts or mid-cast connections.

- on attach, the cast sends its full event log, bracketed by markers that open and close the replay
- the daemon discards any cached state for that cast at the start of the replay and rebuilds it from the log
- after the replay, the daemon continues with live events

## Surviving daemon restarts

As a developer, I want to restart the daemon mid-cast without losing any history, so that the daemon is operationally cheap to recycle.

- running casts reconnect on their own when the daemon comes back
- on reconnect, the cast replays its full log so the daemon's view is complete
- terminated casts remain queryable from disk after a restart

## Inspecting past casts

As a developer, I want to read the full event sequence of any past cast by identifier, so that I can audit or debug after the fact.

- the inspection works even after the daemon has restarted and even after the cast has ended
- the source of truth is the on-disk history, not the daemon's live state
