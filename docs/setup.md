---
description: "A prompt for Claude Code that sets vekna up in your project: install, ritual-scribe, a first ritual and its test."
---

# Setup

Install the ritual-scribe plugin first, then start a new Claude Code session so
it loads:

```bash
claude plugin marketplace add fancysnake/vekna
claude plugin install ritual-scribe@vekna
```

Copy this prompt into that session to set up vekna in your project:

```text
Set up vekna (https://github.com/fancysnake/vekna) in this project.

1. Add `vekna[trial]` as a dev dependency using this project's package
   manager. In a non-Python project, install it as a tool instead, with
   `--include-deps` so pytest lands on PATH, pinned to the version you install:
   - with a `mise.toml`, under `[tools]`:
     `pipx = "<version>"` and
     `"pipx:vekna" = { version = "<version>", extras = "trial", uvx = false, pipx_args = "--include-deps" }`
   - without one: `pipx install --include-deps 'vekna[trial]==<version>'`
2. Load the ritual-scribe skill before writing any ritual.
3. Adapt the `fix_tests` example from
   https://vekna.fancysnake.dev/#your-first-ritual to the command this
   project runs its tests with (task runner, Makefile, package scripts, CI
   config). Add it to the project's `rituals.py` or `rituals/` package, or
   create `rituals.py` at the repo root if there is neither.
4. Add a trial-based test for that ritual next to the project's other tests,
   and make sure pytest can import the ritual, e.g. `pythonpath = ["."]`.
5. Check it: `vekna rituals list` shows `fix_tests`, and the new test passes
   (in a non-Python project, run it with the `pytest` from step 1).
```
