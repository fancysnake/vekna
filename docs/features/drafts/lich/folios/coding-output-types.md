status: draft
updated: 2026-05-24

# Coding agent calls with typed outputs

## Declaring the return shape

As a developer, I want to declare the return shape of a coding call at the call site, so that each call gets exactly the type its caller needs.

- the call accepts plain types (string, integer, float, boolean) and structured types defined by the caller
- the default return type is text, preserving previous behaviour
- the system instructs the agent to produce a value matching the declared shape

## Failing loudly when the reply doesn't fit

As a developer, I want a coding call to raise an error when the agent's reply doesn't validate against the declared type, so that I never silently get back garbage.

- there is no soft-failure path — the result is a valid value or an exception
- the error names what was expected and what was received
- the failed call is recorded in the grimoire log with a failed status

## Keeping telemetry out of the return value

As a developer, I want telemetry to stay in the grimoire log and not contaminate the return value, so that I can write ordinary code against the typed result.

- the returned value carries no metadata about the call
- telemetry (session identifier, tool calls, token counts) is queryable from the grimoire entry by call name
