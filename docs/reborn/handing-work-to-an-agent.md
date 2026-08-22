# Handing work to an agent

See [common.md](common.md) — the `coding` and `shell` Mediums.

The edges of a rite that spends an agent: what the agent may do, what it is
shown, and the discipline that real unattended rituals worked out and vekna
does not teach.

## `disallowed_tools` on `ClaudeOptions`

The skill vekna ships tells a ritual author to **enforce constraints, not
request them**. For command-level denial that is currently impossible: only
`allowed_tools` is exposed, and an allowlist bounds which tools, never what they
may do. So a ritual says *"do not commit and do not push"* in prose in six
prompts, and then carries a step whose whole job is surviving an agent that
committed anyway.

`ClaudeAgentOptions` has carried `disallowed_tools` all along. Adding the field
to `ClaudeOptions` and passing it through `_agent_options` turns
`["Bash(git commit:*)", "Bash(git push:*)"]` into a bound instead of a request,
and the prose in those prompts into a courtesy.

Documentation owes the interaction: `disallowed_tools` beats `allowed_tools` in
the SDK, and it composes with `gate_tools` no better than an allowlist does.

Not sandboxing, still and always — this exposes a declaration, not a jail. See
[common.md](common.md), *Not planned*.

## Shell output, shaped for whoever reads it next

Handing a red gate to an agent should take one call, and the shape of what it
gets should be vekna's decision rather than each author's. A real ritual carries
75 lines whose only job is deciding how much of a gate's output an agent should
see, and `folio/shell`'s own `said` helper is the naive version — both streams,
whole, untrimmed.

What those 75 lines know:

- **Strip ANSI first.** `CI=1` stops most tools colouring; the rest colour
  anyway, and an escape sequence is budget spent on cursor positions.
- **Budget in characters, not lines.** Twenty lines of ruff is a couple of
  hundred bytes; twenty carrying a pytest assertion repr or a mypy note about a
  long generic is orders of magnitude more.
- **Keep the tail, and buy whole lines** — every tool in a `mise` chain puts its
  verdict last, and a tool that pretty-prints onto one long line would otherwise
  spend the budget and hand back nothing.
- **A budget per stream, not one shared.** `mise` puts task chatter on stderr
  and the tool's verdict on stdout; a shared budget is won by whichever is
  longer, which is the chatter.
- **Two readers want two shapes.** The agent wants enough of the end to diagnose
  from; a morning report wants a dozen lines it can scan. One function cannot be
  both.

Ships in `vekna.folio.shell` beside `ShellResult`, because that is where the
callers already stand: ANSI stripping, tail-to-a-character-budget, and the two
shapes named for their readers.

The self-delimiting case stays the author's — a coverage report is cut at its
own banner rather than tailed, because a tail of a work list is an agent asked
to cover lines it was never shown. That is a pattern the docs describe, not a
function.

## The practice, written down

None of this is engine work: it lands on the documentation site and in the
`ritual-scribe` skill, which is what an agent writes rituals from. The finding
is that a downstream comment explaining an upstream limit is the reliable signal
for a missing page.

**Per-step budgets.** Vekna ships one scalar bound. Practice keys a budget dict
on the step's own name, clears it when a step goes green so a step reached twice
starts over, and lets the whole dict die with the item's payload. That
`Step.name` is public and usable is itself undocumented.

**Never route on what the agent said.** The strongest discipline there is, and
nowhere in the docs. Every repair loop re-reads the world: the index decides
whether a conflict is resolved, the gate decides whether it is green, `test -f`
decides whether the agent wrote the file it claimed. The agent's reply is
discarded, deliberately, because nothing reads it. The corollary deserves its
own line: a step with no retry loop has none precisely because there is nothing
to read back.

**Failure is a route, not an exception.** Three tiers, and only the first is a
`RitualError`: fatal to the run (a dirty worktree, a dead CLI), fatal to one item
(a reply that does not fit its schema — one item loses its triage, the night
carries on), and *degraded continuation* — an item that will not go green is
released, reviewed, triaged and reported anyway. This is not a gate and does not
try to fail fast.

**Leave the world recoverable.** [`../safety.md`](../safety.md) covers
credentials and fences and says nothing about the mess. Every give-up path
aborts a half-merge, stashes under a named stash, and puts that name in the
report, because the next item begins with a clean-worktree check and because the
work is not the ritual's to throw away.

**Idempotency in external state.** Labels are how a repeated unattended run
remembers what it already did — and taking one off by hand is how you ask for
the work again. Worth documenting with its reasoning: a label was chosen because
inline review comments are invisible to the API the step could otherwise have
asked.

**Do not pay twice for a verdict you already gave up on.** A failure carried
across items, normalised so two runs of the same broken suite match, so a night
where one thing is broken everywhere pays for that answer once.

**Prompt hygiene**, three items: tell the agent what the *ritual* owns — the
commits, the merge, and the whole-repo sweep the step will run the moment the
agent stops; fence untrusted input as a **standing rule** when the agent fetches
it itself, not only as markers around text the ritual quoted; and scope a session
key to the work item rather than the ritual, or item two's repair agent inherits
item one's context.

**Two small ones.** `max_steps` with the arithmetic written down beats "well
above plausible". And [`../examples.md`](../examples.md) says split by ritual
before splitting by kind, which is right and needs its sequel: when one ritual
outgrows a file it becomes a package split by role — steps, prompts, commands,
state.

### Recorded so it is not mistaken for endorsement

- **The god payload.** Two models threading through every step forces 40 lines
  of hand-written typed-copy helpers, because `model_copy(update=…)` is
  `Mapping[str, Any]` and poisons a strict checker. It contradicts vekna's own
  one-payload-per-shape guidance. Real friction with no good generic fix —
  typing an `evolve` needs a mypy plugin — so it gets documented as a cost, not
  shipped as a helper.
- **A very large `max_steps`.** Safe only because the arithmetic behind it was
  done.

## Out of scope

A typed `evolve` for payloads. Turning any of the practice above into engine
behaviour — each item that deserves that has its own file.

## Acceptance

- A ritual can forbid the agent a command and have the SDK enforce it, with no
  sentence in the prompt doing the work, and the interaction with
  `allowed_tools` and `gate_tools` is documented.
- A red gate is handed to an agent in one call, with no per-ritual trimming;
  colour codes never reach a prompt; a stream that blows its budget loses its
  head, keeps its verdict, and breaks on a line boundary.
- Each practice item above is on a page an author reaches from the site, or in
  `ritual-scribe`, or both, and `emit_delta` and `Step.name` appear in the
  documented public surface.
- `mise run fullcheck` passes.
