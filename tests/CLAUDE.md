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
