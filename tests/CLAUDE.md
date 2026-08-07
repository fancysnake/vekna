# Testing

Test type follows the layer of the code under test. This holds when raising
coverage too — an uncovered line in `gates` / `links` means a missing
**integration** test, never a quick mock-everything unit test of IO-bearing
code.

## Unit tests (`tests/unit/`)

- Yes: mills, specs, pacts (pure logic)
- No: gates, inits
- Links only when the logic is pure and the I/O is injected — a renderer
  formatting to a supplied stream, a probe taking a socket path. A link that
  reaches the network or filesystem on its own belongs in integration.
- Write tests in classes
- Mock at the highest level to avoid side effects
- Check all mock calls

## Integration tests (`tests/integration/`)

- Yes: CLI commands (gates)
- No: pure logic (mills, specs)
- Mock at the lowest level or don't mock if possible
- Check all mock calls and side effects

## Mocking

- Mock external boundaries (third-party SDKs such as `claude_agent_sdk`, at
  their use site), never project code or DI.
- NEVER use `ANY` for simple values (`[]`, `{}`, booleans, strings, ints). Use
  `ANY` only for genuinely hard-to-compare objects.

## Testing a ritual (`tests/integration/rituals/`)

A ritual is never mocked by hand. Take the `trial` fixture (`vekna.trial`, the
`vekna[trial]` extra) — it stands a double where each medium reaches the
outside and nowhere else, so the folio's own body still runs. Integration, not
unit: the mediums are `links`.

- `trial.walk(step, payload)` returns one step's `Transition` and needs no
  ritual — the unit of a step test. `trial.cast(ritual, components)` returns
  the result model, for a path across steps.
- Script before you act: `trial.shell.replies(when="mise run lint*",
  exit_code=0)`, `trial.coding.replies("wrote a test", uses=["Bash"])`,
  `trial.decide.answers(answer=True, when="*proceed*")`. `when=` is a glob
  (`fnmatchcase`); drop it and answers are consumed in order. `always=True`
  keeps one answer standing.
- Assert on what the double recorded — `trial.shell.commands`,
  `trial.coding.prompts`, `trial.coding.gated`, `trial.decide.prompts`. That is
  the "check all mock calls" rule; there is no `assert_called_with` here.
- An unscripted call raises `TrialScriptError` and stops the cast — there is no
  default answer. A `decide` answer outside the offered options raises too.
- The bite: coding's tool gate (`allow tool 'Bash'?`) arrives at
  `trial.decide`, not at `trial.coding` — the folio builds both out of the
  channel.

`.claude/skills/ritual-scribe/SKILL.md` § *Testing a ritual* is the longer
version, with the examples.
