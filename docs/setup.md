---
description: "A prompt for Claude Code that sets vekna up in your project: install, ritual-scribe, a first ritual and its test."
---

# Setup

Copy this prompt into Claude Code to set up vekna in your project:

```text
Set up vekna (https://github.com/fancysnake/vekna) in this project.

1. Add `vekna[trial]` as a dev dependency using this project's package
   manager. In a non-Python project with a `mise.toml`, add it there instead:
   `"pipx:vekna" = { version = "latest", extras = "trial" }` under `[tools]`.
2. Install the ritual-scribe plugin:
   `claude plugin marketplace add fancysnake/vekna`, then
   `claude plugin install ritual-scribe@vekna`. Load the ritual-scribe skill
   before writing any ritual.
3. Find the commands this project uses to test and lint (task runner,
   Makefile, package scripts, CI config).
4. Write a `rituals.py` at the repo root with one ritual, `fix_tests`: run
   the tests, and while they fail, hand the output to the coding medium to fix,
   up to a retry bound.
5. Add a trial-based test for that ritual next to the project's other tests.
6. Check it: `vekna rituals list` shows `fix_tests`, and the new test passes.
```
