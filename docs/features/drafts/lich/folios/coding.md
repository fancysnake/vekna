status: draft
updated: 2026-05-24

# Coding agent calls inside a ritual

## Calling a coding agent

As a developer, I want to ask a coding agent to do work from within a ritual, so that I can drive code edits and analysis without leaving the ritual.

- the call returns the agent's textual reply
- the call can declare an operating mode (e.g. read-only vs editing) so the agent knows what it's allowed to do
- the call can be labeled with a name so it's distinguishable in event output and the grimoire log
- regular conditional code can branch on the reply, alongside shell calls

## Selecting the coding backend

As a developer, I want to choose which coding backend handles requests by enabling it explicitly in my project, so that I control which agent runs without surprise defaults.

- only an enabled backend is used
- swapping to a different backend is a single change in one place

## Approving tool calls

As a developer, I want the system to pause and ask me before the coding agent runs a tool, so that I can review what's about to happen before it does.

- the prompt names the tool and shows its arguments
- I can approve or deny each request
- denial is reported back to the agent as a refused tool call
- only one approval prompt is active at a time

## Auditing coding calls

As a developer, I want every coding call captured in the grimoire log with its full payload, so that I can review later what was asked, what was returned, and how much it cost.

- the payload covers the prompt, mode, response text, and per-call telemetry including a session identifier, tool calls, and token counts
