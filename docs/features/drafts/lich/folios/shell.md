status: draft
updated: 2026-05-24

# Shell commands inside a ritual

## Running a shell command

As a developer, I want to run a shell command from within a ritual, so that I can drive existing tools without leaving the ritual.

- the call waits for the command to finish
- the result exposes success/failure, exit code, standard output, and standard error separately
- regular conditional code can branch on the result

As a developer, I want to label each shell call with a name, so that I can tell calls apart in event output and the grimoire log.

As a developer, I want to set the working directory for a shell call, so that I can run commands against a specific tree without mutating shared process state.

As a developer, I want to set environment variables for a shell call, so that I can pass configuration to the invoked tool without leaking it elsewhere.

## Observing rite execution

As a developer, I want each shell call to emit start and finish markers while the ritual runs, so that I can see what's happening live.

- markers identify the call by name
- the finish marker indicates success or failure

As a developer, I want every shell call captured in the grimoire log with its full payload, so that I can review what ran after the fact.

- the payload covers the command, working directory, environment, exit code, standard output, standard error, and start and finish times
