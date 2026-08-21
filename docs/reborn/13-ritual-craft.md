# Feature — ritual craft: what an outside ritual needed

**Version:** `0.8.0` — **planned**, beside [05-locks.md](05-locks.md). Two
features may share a version; `10` and `12` both took `0.4.0`.

See [00-common.md](00-common.md).

## Where this came from

A project outside this repository casts a ritual called `pr_check`: nightly,
unattended, one pull request at a time — merge the base, make the gates green,
close the coverage gap, post a review, triage the comments, report in the
morning. Around 600 lines across four modules, with 1,500 lines of `trial`
tests behind it. It is the first ritual written by someone who was not also
writing the engine, and the first that is a *queue* rather than a subject.

It works. What it needed to work is the finding. Several of its comments are
folklore about vekna's limits — "the graph is read off each step's source text,
so a target named inside a helper is an edge the drawing loses", "a step checks
rather than trusts, because the agent may have committed anyway" — and a
downstream comment explaining an upstream limit is the reliable signal for a
missing feature. Six of them are below.

The other half of the finding is practice rather than surface, and is filed
under [what the docs owe](#what-the-docs-owe) at the end.

## Goal

Close the six places where a real unattended ritual had to work around the
shipped surface, and write down what it worked out on its own.

## What ships

### 1. `disallowed_tools` on `ClaudeOptions`

The skill vekna ships tells a ritual author to **enforce constraints, not
request them**. For command-level denial that is currently impossible: only
`allowed_tools` is exposed, and an allowlist bounds which tools, never what
they may do. So `pr_check` says *"do not commit and do not push"* in prose in
six prompts, and then carries a step whose whole job is surviving an agent that
committed anyway.

`ClaudeAgentOptions` has carried `disallowed_tools` all along. Adding the field
to `ClaudeOptions` and passing it through `_agent_options` turns
`["Bash(git commit:*)", "Bash(git push:*)"]` into a bound instead of a request,
and the prose in those six prompts into a courtesy.

This is not sandboxing, which stays out of scope for the project
([00-common.md](00-common.md), *Not planned*). It is an SDK knob the author
declares, in the same register as `allowed_tools` — the difference is that one
of the two is currently unreachable through vekna.

Documentation owes the interaction: `disallowed_tools` beats `allowed_tools`
in the SDK, and it composes with `gate_tools` no better than an allowlist does.

### 2. Shell output, shaped for whoever reads it next

`pr_check` carries 75 lines whose only job is deciding how much of a gate's
output an agent should be handed. What is in them is not obvious:

- **Strip ANSI first.** `CI=1` stops most tools colouring; the rest colour
  anyway, and an escape sequence is budget spent on cursor positions.
- **Budget in characters, not lines.** Twenty lines of ruff is a couple of
  hundred bytes; twenty carrying a pytest assertion repr or a mypy note about a
  long generic is orders of magnitude more.
- **Keep the tail, and buy whole lines** — every tool in a `mise` chain puts
  its verdict last, and a tool that pretty-prints onto one long line would
  otherwise spend the budget and hand back nothing.
- **A budget per stream, not one shared.** `mise` puts task chatter on stderr
  and the tool's verdict on stdout; a shared budget is won by whichever is
  longer, which is the chatter.
- **Two readers want two shapes.** The agent wants enough of the end to
  diagnose from; the morning report wants a dozen lines it can scan. One
  function cannot be both.

Vekna's own `src/rituals/shared.py:said` is the naive version — both streams,
whole, untrimmed — and every ritual that hands a gate to an agent will write
the same 75 lines or pay for not having.

Ships in `vekna.folio.shell` beside `ShellResult`, because that is where the
callers already stand: ANSI stripping, tail-to-a-character-budget, and the two
shapes named for their readers. The self-delimiting case stays the author's —
`diff-cover`'s report is cut at its own banner rather than tailed, because a
tail of a work list is an agent asked to cover lines it was never shown — and
that is a pattern the docs describe, not a function.

### 3. `vekna rituals check`

The graph `rituals show` draws is read off each step's source text, matching
`goto` calls whose first argument is a bare name. A `goto` inside a helper is
invisible to it. `pr_check` knows this and writes every `goto(set_aside, …)`
out at its call site to stay drawable — recorded in a comment, enforced by
nothing.

One subcommand over the AST walk `graph.py` already does:

- a step in the compendium that no `goto` reaches;
- a step whose source yields no `goto` and no `done` — either it is dead or its
  transition is hidden in a helper;
- a `goto` naming a target the compendium never registered;
- two sources declaring the same step name, which today is silent and
  first-one-wins.

Best-effort, like the drawing it shares its reader with, and it says so: a
computed target is not an error, it is a thing the check cannot see. Exit
non-zero on a finding, so a ritual library can gate on it.

### 4. The ritual's docstring is its manual, and nothing shows it

`pr_check` opens with 55 lines of operator documentation: what the labels mean,
what ends a branch versus what ends the run, why it asks nothing, how to park a
pull request for a month. It is the best artifact in the file, and no vekna
surface displays a word of it — `@ritual` drops `func.__doc__`, and `Ritual`
has nowhere to put it.

Capture it on `Ritual`, print it under `rituals show`, and take its first line
as the summary in `rituals list`.

This is an exception to the house rule against docstrings, and worth stating as
one: a ritual's entry docstring is not commentary on the code, it is the
interface — the same claim `--help` makes. Making it load-bearing is what keeps
it true.

### 5. An unattended cast says so

`pr_check` declares in its first paragraph that it asks nothing, and gives the
reason: *at 3am a prompt is a hang*. That is a deliberate break with the rule
the skill states — that spending an agent's time is a `decide` — and the break
is correct. What is missing is any way for the ritual to declare it.

Today a `decide` reached from cron gets three empty `readline()`s and dies with
`StandalonePromptError` mid-cast. Not a hang, which is the good half; but it
dies where it stood, and everything the run had accumulated dies with it.

`vekna cast --unattended` makes every `decide` fail at the boundary rather than
at the third empty line, and makes the property visible in the invocation
instead of in a paragraph. The ritual half — a step asking whether it may
prompt — waits on [Hand](../hand/README.md), where failure is a transition.

### 6. A cast that fails still owes its report

`pr_check` routes **every** ending — including the fatal ones — through a
single `report` step that emits the summary and only then raises. It has to:
`RitualError` leaves the step, the CLI prints `cast failed: …`, and the
accumulated result is gone. On a run that reached four pull requests before the
agent died, what is lost is the whole night's work product.

Two answers, and the cheap one first:

- **Document the pattern.** One terminal step, every ending routes to it,
  `emit_delta` the human summary, `done` or raise last. It costs nothing and it
  is what the ritual already does. `emit_delta` is exported from the lexicon
  and appears in no page under `docs/` — that alone is worth fixing.
- **Let `RitualError` carry a payload**, rendered by the CLI the way `done`'s
  result is. Small, additive, and it removes the reason the terminal step has
  to exist. Weigh against [Hand](../hand/01-failure.md), which is where failure
  stops being an exception at all — if failure-as-a-transition lands, this is
  subsumed. File it as the fallback, build it only if Hand stays parked.

## What the docs owe

Everything below is practice `pr_check` worked out and vekna does not teach.
None of it is engine work. It lands in the documentation inventory that
[08-hardening.md](08-hardening.md) holds and [09-site.md](09-site.md)
publishes, and in the `ritual-scribe` skill, which is what an agent writes
rituals from.

**The queue ritual.** None of the four shipped examples fans out over a work
list, and the workflows vekna is aimed at — nightly triage, merge babysitting —
all are. The shape, as `pr_check` found it: a run-level accumulator, a fresh
per-item payload that *dies with the item* so budgets reset by construction,
items dropped at the listing rather than skipped later (a parked branch is then
never checked out, never counted, never in the report), the queue ordered by
staleness, and one terminal report every ending routes to. This is the missing
fifth example ritual, not just a page.

**Per-step budgets.** Vekna ships one scalar `Bound`. `pr_check` keys a budget
dict on the step's own name, clears it when a step goes green so a step reached
twice starts over, and lets the whole dict die with the item's payload. That
`Step.name` is public and usable is itself undocumented.

**Never route on what the agent said.** The strongest discipline in the file
and nowhere in the docs. Every repair loop re-reads the world: the index
decides whether a conflict is resolved, the gate decides whether it is green,
`test -f` decides whether the agent wrote the file it claimed. The agent's
reply is discarded, deliberately, because nothing reads it. The corollary
deserves its own line: the one step in `pr_check` with no retry loop has none
precisely because there is nothing to read back.

**Failure is a route, not an exception.** Three tiers, and only the first is a
`RitualError`: fatal to the run (a dirty worktree, a dead CLI), fatal to one
item (a reply that does not fit its schema — one branch loses its triage, the
night carries on), and *degraded continuation* — a branch that will not go
green is released, reviewed, triaged and reported anyway. *"This is not a gate
and does not try to fail fast."*

**Leave the world recoverable.** [`safety.md`](../safety.md) covers credentials
and fences and says nothing about the mess. Every give-up path in `pr_check`
aborts a half-merge, stashes under a named stash, and puts that name in the
report, because the next item begins with a clean-worktree check and because
the work is not the ritual's to throw away.

**Idempotency in external state.** Labels are how a repeated unattended run
remembers what it already did — and taking one off by hand is how you ask for
the work again. Worth documenting with its reasoning: a label was chosen
because inline review comments are invisible to the API the step could
otherwise have asked.

**Do not pay twice for a verdict you already gave up on.** A failure carried
across items, normalised so two runs of the same broken suite match, so a night
where one thing is broken everywhere pays for that answer once.

**Prompt hygiene**, three items: tell the agent what the *ritual* owns — the
commits, the merge, and the whole-repo sweep the step will run the moment the
agent stops; fence untrusted input as a **standing rule** when the agent
fetches it itself, not only as markers around text the ritual quoted; and scope
a session key to the work item rather than the ritual, or item two's repair
agent inherits item one's context.

**Two small ones.** `max_steps` with the arithmetic written down beats "well
above plausible". And [`examples.md`](../examples.md) says split by ritual
before splitting by kind, which is right and needs its sequel: when one ritual
outgrows a file it becomes a package split by role — steps, prompts, commands,
state — which is what `pr_check` did.

## Not copied

Recorded so the next reader of that ritual does not take these for
endorsements.

- **The god payload.** Two models thread through every step, which forces 40
  lines of hand-written typed-copy helpers, because `model_copy(update=…)` is
  `Mapping[str, Any]` and poisons a strict checker. It contradicts vekna's own
  one-payload-per-shape guidance, and the file says so in a comment. Real
  friction with no good generic fix — typing an `evolve` needs a mypy plugin —
  so it gets documented as a cost, not shipped as a helper.
- **`max_steps = 240`.** Safe only because the arithmetic behind it was done.

## Out of scope

- Sandboxing, still and always. Item 1 exposes a declaration, not a jail.
- A ritual-side unattended check (`if not may_prompt()`). That is failure as a
  transition, and it is [Hand's](../hand/01-failure.md).
- A typed `evolve` for payloads. See *Not copied*.

## Acceptance

- A ritual can forbid the agent a command and have the SDK enforce it, with no
  sentence in the prompt doing the work.
- Handing a red gate to an agent takes one call, and the shape of what it gets
  is vekna's decision rather than each author's.
- `vekna rituals check` fails a ritual whose `goto` is hidden in a helper.
- `vekna rituals show pr_check` prints what its author wrote for its operator.
- A cast that ends in failure still puts its report in front of the human.
- The four example rituals are five, and the fifth is a queue.
