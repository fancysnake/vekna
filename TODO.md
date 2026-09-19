# TODO

- DSL-based workflow orchestrator for agents

## Friction

- `coverage` stops tracing a coroutine's frame after it awaits another
  coroutine whose `finally` does `task.cancel()` then `await task` under
  `contextlib.suppress(CancelledError)` — every line after that await reports as
  missed although it demonstrably runs. Reproduced in 21 lines outside pytest.
  `await asyncio.gather(*tasks, return_exceptions=True)` traces fine, so that is
  what the daemon uses.
- `tingle`'s `type-cast` metric counts every symbol named `cast`, not just
  `typing.cast`. Naming a `CastView` parameter `cast` — the domain word this
  project is built on — read as +25 typing debt and failed `fullcheck`. Worked
  around by calling them `view`; the metric wants a way to say "this symbol,
  imported from this module".
- Adding `jq` to mise `[tools]` made `mise install` fetch it through aqua,
  which verifies GitHub artifact attestations against sigstore's TUF root. From
  the sandboxed shell that endpoint was unreachable, so every `mise run` and
  `mise exec` aborted until `MISE_DISABLE_TOOLS=jq` was set. Worked outside the
  sandbox; log it if it recurs.
