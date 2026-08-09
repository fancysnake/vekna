# Safety, and what vekna does not sandbox

**Vekna does not sandbox agents.** The agent edits your repository and runs
your commands — that is the job, and a sandbox around it would defeat the
point.

What the process split does buy is containment of *failure*: a broken ritual or
a misbehaving SDK kills one cast process and nothing else.

Where a boundary is genuinely wanted, two things work, and neither is vekna's
to build.

## Scope the credentials, not the process

A ritual that triages pull requests needs a token that can read pull requests
and comment on them — not one that can push to `main` or read every repository
in the organisation.

Fine-grained tokens, one per ritual, least privilege. The
[example rituals](examples.md) each state the exact permission set they need,
because a recommendation nobody can act on is not a recommendation.

## Fence the whole thing if you want a fence

If a cast must not reach the host, run *vekna* inside the container —
devcontainer, VM, whatever the project already uses — rather than expecting
vekna to grow one inwards. A cast process is an ordinary Python process with a
working directory, and it containerises like anything else.

## What vekna does own

Small, and stated:

- The `coding` medium's tool gate. `CodingOpts(gate_tools=[...])` asks you
  before the agent runs a named tool, and `permission_mode="dontAsk"` with an
  `allowed_tools` list denies everything outside it without stopping to ask.
  That is how you get a genuinely read-only agent — the list doing the work,
  not the mode: `dontAsk` denies what is not on it and grants what is, so one
  write-capable tool in there is a write-capable agent.
- A `decide` never defaults and never times out. Nothing in a cast answers a
  question on your behalf.
- Step budgets. `max_steps` bounds the trampoline, so a ritual that loops
  forever stops rather than running until you notice.

None of these is a sandbox. They are places where you get to say no.
