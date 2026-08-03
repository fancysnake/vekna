# Vekna's own rituals

This project casts them on itself.

```bash
vekna cast cover_diff [--bound N]
vekna cast review [--base <ref>] [--only <file>] [--focus <text>]
vekna cast merge_ready [--bound N]
vekna cast triage --link <url>
```

- [`cover_diff`](cover_diff.py) closes the coverage gap on the current
  branch: measure with `diff-cover`, hand the uncovered lines to an agent,
  measure again.
- [`review`](review.py) reads the diff this branch adds and returns findings
  under a schema. Its agent is read-only, enforced by the allowlist rather
  than asked for in the prompt.
- [`merge_ready`](merge_ready.py) runs both gates at once and babysits them to
  green. Whichever went red picks the payload shape the repair step receives.
- [`triage`](triage.py) reads a GitHub issue or PR with `gh`, has an agent
  size it against this codebase, and asks you what it deserves.

Every one of them holds to the same bargain. The agent works permissively
inside its step — it edits files and runs commands without stopping for
permission, unless a call's `CodingOpts` names `gate_tools` — and it can put a
question to you mid-step through `ask_human`, which every `coding` call
offers. What happens next is decided at the step boundary: a gate passes or it
does not, a budget runs out, you answer a `decide`. Agents are
non-deterministic inside a step and deterministic between them.

Concurrency lives inside a step too, and needs nothing from the engine: see
[`merge_ready.gates`](merge_ready.py), which starts two shells in an
`asyncio.TaskGroup` and waits for both. Each opens its own rite, because a
Task copies the contextvar the runtime hangs them from.

## Layout

One module per ritual, and its models, steps and helpers stay together in it.
Prompt text lives in [`prompts.py`](prompts.py) instead: a block of prose
between two steps hides what the steps do. [`shared.py`](shared.py) holds what
more than one ritual uses, which is one type.

`__init__.py` is empty and stays that way — the engine sweeps every submodule,
so nothing needs re-exporting to be found.
