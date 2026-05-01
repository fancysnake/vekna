status: draft
updated: 2026-05-24

# Declaring lock exclusivity in a ritual

## Claiming a lock around a section of work

As a developer, I want to claim a named lock for a scoped block of code in my ritual, so that the work inside is exclusive while it runs.

- the lock is held for the duration of the block and released when the block exits
- the lock is owned by the whole cast, not the call that took it
- conflicting nested claims inside one cast (e.g. taking a broader scope while a narrower one is held) raise

## Naming locks hierarchically

As a developer, I want lock names to be hierarchical with colon-delimited segments, so that the same vocabulary expresses both broad and narrow exclusivity.

- holding a parent name blocks claims on its ancestors and descendants
- siblings under the same parent are independent and can be held simultaneously
- I can compose names from segments using a helper or write them as plain strings

## Knowing locks aren't coordinated yet

As a developer, I want a clear, one-time warning when my ritual takes a lock without a coordinator running, so that I'm not surprised when two concurrent casts run unsafe work side-by-side.

- the warning appears once per cast, never per lock
- the warning explains why standalone locks are unsafe and how to enable coordination
- the warning is the default behaviour for an interactive run

## Choosing how uncoordinated runs behave

As a developer, I want to configure how lock acquisitions behave when no coordinator is running, so that scripts, interactive sessions, and strict runs each behave appropriately.

- silent mode: locks succeed locally without any warning, suitable for scripts
- warning mode: locks succeed locally with the one-time warning, the default for interactive use
- strict mode: lock acquisition refuses to proceed and prompts the operator to retry the connection or quit the cast
- the choice is configurable per-project and per-user, with the project setting taking precedence
- a per-invocation override beats both
