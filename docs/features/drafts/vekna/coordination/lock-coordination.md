status: draft
updated: 2026-05-24

# Cross-cast lock coordination

## Blocking on a contended lock

As a developer, I want a second cast asking for the same lock to block until the first releases it, so that concurrent casts can rely on exclusivity rather than just declaring it.

- the daemon is the authoritative arbiter of lock state
- the first cast acquires the lock and proceeds
- a second cast trying to acquire the same key blocks until the first releases
- on release, the next waiter is granted the lock and continues

## Independent sibling locks across casts

As a developer, I want siblings under the same parent lock to be independent across casts, so that two casts can run non-overlapping work in parallel.

- two casts holding sibling keys both proceed at the same time
- the hierarchical conflict rules from the lock API are honoured across casts the same way they were honoured within a single cast

## Recovering lock state through replay

As a developer, I want lock state to be reconstructed automatically when the daemon restarts, so that an outage doesn't leak or lose held locks.

- the daemon rebuilds lock state from the cast event replay, not from a stored snapshot
- a cast that was holding a lock before the restart still holds it afterwards
- contending casts still block correctly after the rebuild

## Coordinated runs as the default

As a developer, I want strict coordination to be the default when the daemon is the expected runtime, so that the safe behaviour is the one I get without thinking about it.

- when configuration is unspecified, an absent daemon causes lock acquisition to halt and prompt the operator
- previous defaults (silent / warning) remain available to opt into explicitly

## Inspecting current lock activity

As a developer, I want to list current lock holders and pending requests, so that I can see who's holding what and who's waiting.

- the listing shows holder identifier, lock name, and acquisition time
- pending waiters are listed alongside holders

## Releasing a stuck lock as an admin

As a developer, I want to forcibly release a lock when the holder is stuck or gone, so that I can recover without restarting everything.

- the release is gated by an explicit confirmation prompt
- the holding cast receives an event explaining the release was an admin override
- the release is recorded in the cast's history with the override reason
