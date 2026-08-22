# Failure as a transition

See [`../reborn/common.md`](../reborn/common.md) — ritual model,
transitions, the bounded trampoline.

## Goal

A step that raises kills the cast. For a cast running unattended that is the
wrong default: "the agent failed, log it, try again with a narrower scope" is
the *normal* path in a PR-triage or migration ritual, not the exception. Today
the only way to express it is `try/except` in every step body, which puts
routing back inside the step after the engine spent a release taking it out.

Give failure the shape everything else in the engine already has — a typed
payload and an edge in the graph.

## What ships

- **`@step(on_error=<step>)`** — names the step a failure routes to. Absent, a
  raise behaves exactly as it does now: the cast aborts, non-zero exit, the
  traceback reported rather than swallowed.
- **`Failure[T]`** — the payload the recovery step receives:

  ```python
  class Failure[T](BaseModel):
      error: ErrorInfo       # type, message, traceback text
      rite: RiteRef          # which rite raised, and where in the grimoire
      payload: T             # the value that entered the failed step
      attempt: int           # how many times this step has failed in this cast
  ```

  `payload` is the point. Recovery that cannot see what went in can only log;
  recovery that can see it can narrow the scope and go again.

- **Recovery is an ordinary step.** It takes a `Failure[T]` and returns a
  `Transition` like anything else — `goto` back to retry, `goto` elsewhere to
  fall back, `done` to give up having written a report:

  ```python
  @step(on_error=triage)
  async def claude_fix(a: Attempt) -> Transition:
      await coding(f"fix:\n{a.failures}")
      return goto(run_tests, Attempt(failures="", budget=a.budget))

  @step
  def triage(f: Failure[Attempt]) -> Transition:
      if f.attempt >= 3:
          return done(Report(fixed=False, reason=f.error.message))
      return goto(claude_fix, f.payload.narrowed())
  ```

- **`on_error` edges are real edges.** They appear in `rituals show` and in the
  graph the Eye renders — see
  [`../eye/workflow-graph-drawn.md`](../eye/workflow-graph-drawn.md) — because a
  recovery path that is invisible in the graph is a recovery path nobody
  reviews.
- **The budget guard still counts.** Recovery re-entering a step counts against
  `max_visits` and the transition against `max_steps`, so a retry loop is
  bounded by the machinery that already bounds loops. `on_error` introduces no
  new way to hang, and a recovery step that fails routes to *its* `on_error` or
  aborts — no implicit self-catch.
- **Three outcomes, deliberately distinct.** Escalate (no `on_error`: the cast
  dies, and that is correct for a corrupt repo), recover (route to the recovery
  step), and convert — a timeout arrives *as* a `Failure`
  ([bounding-a-rite.md](bounding-a-rite.md)), a budget overrun likewise
  ([budgets-and-processes.md](budgets-and-processes.md)), so one mechanism
  handles all three.
- **Locks release.** A step failing inside `async with lock(...)` releases on
  the way out, as the context manager already guarantees; the release event is
  in the grimoire before the failure transition is.
- **Grimoire and wire.** `RiteFailed` carries the error; the move into recovery
  is an ordinary transition event. The daemon shows a cast in recovery as
  running-with-a-failure, not as failed, and `vekna casts` distinguishes the
  two.

## A cast that fails still owes its report

A ritual that reached four items before the agent died loses the whole night's
work product: `RitualError` leaves the step, the CLI prints `cast failed: …`,
and the accumulated result is gone. So rituals route **every** ending —
including the fatal ones — through a single terminal `report` step that emits
the summary and only then raises.

Two answers, and the cheap one first.

- **Document the pattern.** One terminal step, every ending routes to it,
  `emit_delta` the human summary, `done` or raise last. It costs nothing and it
  is what real rituals already do. `emit_delta` is exported from the lexicon and
  appears on no page under `docs/` — that alone is worth fixing.
- **Let `RitualError` carry a payload**, rendered by the CLI the way `done`'s
  result is. Small, additive, and it removes the reason the terminal step has to
  exist. It is filed here because `on_error` subsumes the second half: once
  failure is a route, the terminal step is reachable by an edge and the payload
  rides an ordinary transition.

## An unattended cast says so

A ritual meant for cron declares in its first paragraph that it asks nothing,
because at 3am a prompt is a hang. That is a deliberate break with the rule that
spending an agent's time is a `decide`, and the break is correct. What is
missing is any way for the ritual to declare it.

Today a `decide` reached from cron gets three empty `readline()`s and dies with
`StandalonePromptError` mid-cast. Not a hang, which is the good half; but it
dies where it stood, and everything the run had accumulated dies with it.

- **`vekna cast --unattended`** makes every `decide` fail at the boundary rather
  than at the third empty line, and makes the property visible in the invocation
  instead of in a paragraph.
- **The ritual-side half** — a step asking whether it may prompt — is why this
  is filed here rather than beside the CLI: a `decide` that cannot be answered
  becomes a `Failure` with an `on_error` route, and a ritual that would rather
  degrade than die says so with an edge.

## Scope

- `lexicon/_pacts.py` — `Failure`, `ErrorInfo`, `RiteRef`; a payload on
  `RitualError`.
- `lexicon/_mills/` — the trampoline catches at the step boundary, builds the
  `Failure`, validates it against the recovery step's input annotation like any
  other payload, and dispatches.
- `lexicon/_gates.py` — `rituals show` draws `on_error` edges; the CLI renders a
  failure payload the way it renders a result; `cast --unattended`.
- `wire/_pacts.py` — `RiteFailed`.
- Daemon `mills/` — cast state gains "recovering".

## Out of scope

Retry policy as configuration — no `retries=`, no backoff, no jitter. The
recovery step is Python; if it wants to sleep before going again it can say so,
and a decorator argument would only be a worse language for the same thing.

Compensation and rollback (sagas). Undoing a half-finished edit is the ritual's
business and, for a repo, git's. Cross-cast failure escalation — one cast's
failure is not another's, and the daemon already surfaces both.

## Acceptance

- A step raising with no `on_error` aborts the cast exactly as before: non-zero
  exit, error reported, grimoire closed.
- A step raising with `on_error` routes to the recovery step; the `Failure`
  carries the entering payload, and a `goto` back into the failed step re-runs
  it with the narrowed value.
- `attempt` increments across repeated failures of the same step in one cast.
- A recovery loop that never converges stops on `max_visits` with
  `StepBudgetExceededError`, not by hanging.
- A step failing while holding a lock releases it; the daemon shows the lock
  free before it shows the failure.
- A failure inside the recovery step itself routes to *its* `on_error` if it
  declares one, and otherwise aborts the cast — never an implicit self-catch.
- `rituals show` prints the `on_error` edge; a recovery step reachable only that
  way is not reported as unreachable.
- A cast that ends in failure still puts its report in front of the human, and
  the terminal-report pattern is written down on a page a ritual author reads.
- `vekna cast --unattended` on a ritual that reaches a `decide` fails at that
  boundary, naming the prompt it refused to ask; without the flag nothing
  changes.
- `mise run fullcheck` passes.
