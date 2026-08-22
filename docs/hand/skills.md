# Skills: procedures a rite loads on demand

See [`../reborn/common.md`](../reborn/common.md) — the
`coding` Medium and its call shape.

## Goal

Today a procedure has to be in the prompt string. A `coding` rite that might
need to do any of six things carries all six procedures in every prompt, and the
agent reads all six to do one. The prompt grows, the relevant part gets
proportionally quieter, and the step that was supposed to be a bounded task
starts behaving like a briefing.

Advertise the procedures; load the one that gets picked.

## What ships

- **`skills=` on the `coding` Medium** — part of the portable call shape, not a
  Focus knob:

  ```python
  await coding(prompt="...", skills=["./skills/migrate", "./skills/review.md"])
  ```

  A bare directory means every skill under it.
- **Progressive disclosure.** The Focus advertises each skill's *description*
  and a tool to load one; the body enters context only when the agent asks for
  it. A rite offering ten skills carries ten sentences, not ten procedures.
- **Two formats on disk**, deliberately the ones a repo may already have:
  - a flat `.md` file — the content is the procedure, and the first non-empty
    line is its description;
  - a directory holding `SKILL.md` with `description` frontmatter, plus whatever
    references, scripts and assets the procedure points at.
- **The description is a routing hint, not a label.** Written as the task that
  should trigger it — "convert a class component to hooks, preserving refs" —
  because it is the only thing the agent sees before choosing. This is
  documented as a rule, and `vekna rituals show` prints the descriptions so a
  bad one is visible without casting anything.
- **A skill load is a rite.** It emits into the grimoire like any other, so the
  daemon, the Eye, and the journal all show which procedure the agent reached
  for and when. That is vekna's addition rather than the convention's: the
  choice becomes observable, reviewable after the fact, and — because it is in
  the journal — replayable ([replay.md](replay.md)).
- **Portable at the Medium.** A Focus that cannot do progressive disclosure
  inlines every advertised skill into the system prompt and says so once, at the
  first call. Degrading is fine; pretending is not.
- **`./skills/` by convention**, `[skills] paths = [...]` in `.vekna.toml` to
  say otherwise, resolved the same way `[rituals]` is.

## Why not put them in the ritual

Because the ritual is the part that must stay deterministic. A procedure is
prose the agent reads inside a step, which is exactly the region where the
bargain vekna already makes says the agent runs permissively. A
skill changes what the agent knows; it does not change where the step boundary
is or what crosses it. Nothing in the engine moves for this feature.

## Scope

- `folio/coding/{_pacts,_mills}.py` — `skills=`, the skill manifest model,
  description extraction, path resolution.
- `folio/coding_claude/_links.py` — advertising descriptions and serving the
  load tool through the SDK.
- `lexicon/_specs.py` — the `[skills]` config table.
- `lexicon/_gates.py` — `rituals show` lists the skills a ritual's rites offer.
- Grimoire: a skill-load rite kind.

## Out of scope

Skills that execute. A skill is a procedure the agent *reads*; if it should run,
it is a Medium, and the folio boundary is where that gets decided. A registry,
index or marketplace — skills are files in the repo that needs them. Skills on
any Medium but `coding`; `shell` does not read prose.

## Acceptance

- A rite offering three skills sends three descriptions and no bodies; the
  transcript shows the body arriving only after the agent asks for it.
- The chosen skill appears in the grimoire as its own rite, with its name, and
  survives into the journal.
- A flat `.md` with no frontmatter is advertised by its first line; a packaged
  skill with no `description` frontmatter is rejected at the call with the path
  named, not skipped silently.
- A directory path picks up every skill beneath it, including packaged ones.
- Against a Focus without progressive disclosure, everything still works, the
  bodies are inlined, and the one-time notice appears once per cast.
- `vekna rituals show` prints skill descriptions.
- `mise run fullcheck` passes.
