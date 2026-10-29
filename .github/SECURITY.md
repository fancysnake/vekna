# Security policy

## Reporting a vulnerability

Report it privately through
[GitHub's advisory form](https://github.com/fancysnake/vekna/security/advisories/new),
not in a public issue. Expect a reply within a week.

## Supported versions

Only the latest release receives fixes.

## Scope

Vekna does not sandbox agents: a ritual's agent edits your repository and runs
your commands by design. [Safety](https://vekna.fancysnake.dev/safety/) lists
what vekna does guard. A way around one of those guards is a vulnerability; an
agent doing what its ritual allows is not.
