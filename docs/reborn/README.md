# Reborn — `1.0.0`

The roadmap for vekna's pivot to overseeing many concurrent rituals. Common
knowledge lives once; each feature doc assumes it. One `vekna` binary, three
roles: the `vekna cast` process runs one ritual; the `vekna` daemon observes
casts, coordinates locks, owns the journal; a **lich** stands in one directory
and casts on command, from a terminal or from Discord.

- [00-common.md](00-common.md) — premise, vocabulary, process model, package
  layout, layering, wire protocol, Components, config, standalone, CLI (incl.
  the Hand/Eye path), deps, resolved decisions, not-planned.

Every feature, its version and whether it exists are in the
[roadmap](../README.md#roadmap), across all three tracks at once. What is below
is only what a table cannot hold: why the numbering reads the way it does. 1.0
ships when every Reborn feature is ready — not when the daemon lands.

## How the numbering came to be this

- **`04` is an empty doc slot.** `folio/process` moved to Hand as
  [`../hand/06-process.md`](../hand/06-process.md): owning a process is
  cancellation plus bounds, and both of those are Hand's already. The slot keeps
  its number rather than closing up, so every number below it still means what
  it did. The *version* it vacated went to
  [10-ritual-modules.md](10-ritual-modules.md), which was built first. `coding`'s
  session declaration, filed here as the other half of `0.4.0`, shipped in
  `0.3.0` instead — see [03-coding-folios.md](03-coding-folios.md).
- **`10` and `12` are numbered last and shipped early.** Both took `0.4.0`. The
  doc slots below them were spoken for by features that are not written; the
  version is what orders a release, not the filename.
- **`01` was superseded by the release after the one that shipped it.** The tmux
  subsystem it re-rooted was removed in `0.3.0`, so the subgroup no longer
  exists. What it was for — freeing the top-level `vekna` — still holds.
- **`09` and the publishing half of `08` took `0.5.0`, off the 1.0 line, and
  locks, the daemon and the lich each slid a slot to make room.** Vekna is in
  use somewhere that is not this repository, and a checkout is no way to install
  it, so PyPI and the site come forward. `0.5.0` rather than a patch number
  because this is the first version anyone outside this repository installs by
  name, and that is worth a minor. The rest of `08` stays where it is.
- **The daemon and locks swapped, and locks got simpler for it.** Locks were
  next and are not what is needed next, so `0.6.0` is the daemon and `0.7.0` is
  locks; nothing below moves, and the lich keeps `0.8.0`. Landing after the
  coordinator rather than before it deletes a whole stage from
  [05-locks.md](05-locks.md) — there is no permissive default to ship and then
  flip, and no release where `lock()` succeeds while promising nothing.
- **`13` is numbered last because it was found last.** Casting a real ritual
  from outside this repository turned up six places the shipped surface has to
  be worked around; they are small, independent of everything else on the line,
  and filed at `0.7.0` beside locks rather than given a slot of their own.
- **`14` shares `13`'s number-neighbourhood and its provenance.** The same
  outside tome that turned up the six workarounds wants one component answered
  per repository rather than per run. Filed separately because it is a config
  surface rather than a ritual-authoring one, at `0.7.0` beside it.
- **Nothing below `0.5.0` has started, but some of it is in the tree.** The wire
  already carries the lock messages, and a cast already probes for a daemon it
  cannot yet find. Groundwork laid early by the feature that needed the seam,
  not a feature half-shipped.

## Undecided

- [11-steps-as-dto.md](11-steps-as-dto.md) — steps return the next step as a
  value, so a return type declares a ritual's edges instead of a parser
  inferring them. Competes directly with
  [`../eye/04-graph.md`](../eye/04-graph.md)'s `@step(goes_to=[...])`; exactly
  one should be built, and both wait on rituals entering mypy's scope. Filed
  here rather than in the roadmap because it breaks the public ritual API, and
  that is a decision to take before 1.0 fixes it — not a feature 1.0 waits for.

## Parked

[`../eye/`](../eye/README.md) — **Eye** (`2.0.0`), the surfaces that watch:
Textual TUI, web view, the lich's web page, the workflow graph drawn, and the
lich's channels reshaped into adapters. Same wire, same events, another
consumer, so they park without blocking anything here. WhatsApp notifications
were dropped outright: Discord ships at 0.8.0 and does that job better.

[`../hand/`](../hand/README.md) — **Hand** (`3.0.0`), the acting half: failure
as a transition, `timeout`/`race`, cast budgets, loadable skills, and replaying
a recorded cast to check the ritual still walks its path. Engine work, filed
past 1.0 so a second syntax does not land halfway through getting the first
story finished.
