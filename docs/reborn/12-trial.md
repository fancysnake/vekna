# Feature — Trial: testing rituals

**Version:** `0.4.0`

See [00-common.md](00-common.md) — package layout, layering, Components.

A complementary release rather than a roadmap slot. Nothing a `0.3.0` ritual
does changes: the surface is additive, and the one existing behaviour it
touches (`shell` resolving a Focus) keeps its present default. It ships beside
the roadmap because what it fixes — rituals having no way to be tested — gets
worse with every ritual written.

## Goal

A ritual is a program, `vekna cast` is the only way to run one, and running one
spends an agent, a shell and a human. So the four rituals in this repo's
`rituals.py` — 518 lines, 9 steps — have no tests, and neither can anyone
else's. They are not in `[tool.coverage.run] source` either: the one file in
this repo that uses vekna the way an author does is the one file no gate looks
at.

The pieces exist, unshipped — this repo's suite hand-rolls them:

| Hand-rolled | Where | Call sites |
|---|---|---|
| `entry(target=…, payload=…)` — a throwaway ritual to reach one step | `tests/conftest.py` | 20 |
| `FakeFocus` — a scripted coding agent | `tests/unit/folio/coding/test_coding.py` | 1 of a kind |
| `_cast(...)` — grimoire, renderer, `asyncio.run` | 3 test modules | copied |
| `_isolated_registry` — reset the focus registry around a test | 2 test modules | copied |

All of it private to this repo, none of it typed (`tests/**` is exempt from
`ANN`), and none of it reaching an author who installed the wheel.

Ship the seam an author needs to run a ritual with the mediums answering from a
script, and to assert on what the ritual asked for.

## What ships

- **`vekna.trial`** — a fifth package. `Trial`, three doubles, one pytest
  fixture, and nothing else on the public surface.
- **`trial.cast(ritual, components)`** runs a whole cast in-process and returns
  the result model; **`trial.walk(step, payload)`** runs one step and returns
  its `Transition`.
- **Doubles at the folio's outer edge** — `trial.coding`, `trial.shell`,
  `trial.decide`. The medium's own body still runs.
- **A Focus seam for `shell`.** `ShellCall`, `ShellReply` and
  `ShellFocusProtocol` in the lexicon's pacts beside coding's; `BashFocus` in
  `folio/shell/_links.py`; `shell()` resolving a Focus **with `BashFocus` as
  the default**, so an unregistered `shell()` behaves exactly as it does today.
- **`SHELL_FOCUS.scope(focus)`** in the lexicon — install a Focus for the
  duration of a block and put back what was there.
- **An unscripted call raises.** `TrialScriptError` names the call and what the
  script still held.
- **Every call is recorded** — `trial.coding.calls` are real `CodingCall`s,
  `trial.shell.commands` the commands as issued, `trial.decide.asked` the
  prompts as offered — alongside `trial.steps`, `trial.deltas`, `trial.events`
  and `trial.result`.
- **A pytest plugin** offering one fixture, `trial`. pytest is an optional
  extra: `pip install vekna[trial]`.
- **Tests for this repo's four rituals**, written with it.
- **`rituals.py` moves to `src/rituals.py`** and joins the coverage report,
  held to the same diff-coverage bar as the package. A root `.vekna.toml`
  points the engine at it.

## Why each one

**Two entry points, not one.** A step is where a ritual's decisions are, a cast
is where its path is. `walk` answers "given this payload, where does `measure`
go?" without a ritual wrapper — what `entry()` is for at 20 call sites, written
out three lines at a time — and is what makes a 130-line step testable at all:
the alternative is scripting every medium call in the ritual to reach the third
step. `cast` answers "does `merge_ready` repair once and then go green?", which
no per-step test can.

**Doubles at the folio edge, not at the medium.** Intercepting `coding(...)`
itself would be smaller and would test nothing: session threading, `resume`
resolution, output-schema validation and exit-code handling all live in the
medium body, and a ritual that mis-declares `session=Session.CONTINUE` would
pass a test that skipped them. Standing the double where the Claude SDK stands
keeps that body under test — `trial.coding.calls[1].resume` is how a test
proves the second call joined the first one's thread.

**`shell` has no seam at all.** `shell()` calls `run_bash` in the same `_links`
module, so today the only way in is monkeypatching a private symbol. Coding's
boundary types already live in the lexicon's pacts — the shape that lets
`coding_claude` implement a Focus without importing a folio. Written a second
time it gives `trial` a supported way in and costs the shell folio one
indirection. `BashFocus` as the resolution default is what keeps it free:
`FocusMissingError` is right for an SDK that may not be installed and wrong for
bash, and a `shell()` call in a cast that loaded no folios must keep working.

**`scope`, because a leaked double poisons the next test.** The slot has
`register` and a wholesale `reset_registry`, nothing between them. A
trial that reset would clobber a focus the author registered; one that only
registered would leave a scripted agent installed for whatever ran next.
Install-and-restore is the operation, so it becomes one.

**Matching by pattern, not only by arrival.** `merge_ready.gates` starts both
gates in an `asyncio.TaskGroup`:

```python
async with asyncio.TaskGroup() as group:
    linting = group.create_task(shell("mise run lint:py"))
    suite = group.create_task(shell("mise run test:py"))
```

Which lands first is the scheduler's business, so a queue keyed on arrival
order makes that test flaky by construction. Each double takes answers `when=`
a pattern — the command for `shell`, the prompt for `coding` and `decide` — and
falls back to an ordered queue for calls no pattern claims. Matched answers
win; each is consumed once, unless it says `always=True`.

**An unscripted call raises, and never defaults.** A double returning
`exit_code=0` for a command nobody scripted would send `cover_diff` down the
covered branch and report a pass; one returning `exit_code=1` would loop
`merge_ready` until `max_steps=32` and report a budget failure. Neither says
what was missing. `TrialScriptError` names the call, the pattern that would
have matched it, and what the script still held.

**A scripted answer is checked against the options.** `decide` returns a member
of what it offered or raises — the real `Channel`'s contract. A test scripting
`"repair"` for a step that offers `["fix", "stop"]` is testing a ritual that
does not exist, so the double refuses it the way the channel would.

**The reply may be a model.** `judge` calls `coding(..., output=Judgement)`,
and the Focus answers with text the medium validates against the schema.
`trial.coding.replies(Judgement(verdict="ship", findings=[]))` serialises the
model, so the test says what it means and that validation still runs on the way
back.

**The double reaches its script through a contextvar.** `CodingFocusProtocol`
declares `run` as a `@staticmethod` — a real Focus carries no per-call state —
and a class implementing a protocol must declare it as a base, so a double with
an instance method would not type-check. `src/` is checked under the strict
config and `tests/` is not, which is why `FakeFocus` gets away with it today
and `vekna.trial` cannot. The double stays static and reads the active `Trial`
from a contextvar, the mechanism the engine already uses for the rite context.
The alternative is relaxing a shipped protocol for a test double's convenience.

**A fixture and a plain object.** The fixture is what a pytest user wants;
`Trial` as a context manager is what everyone else needs, and what keeps the
plugin a five-line wrapper rather than the feature.

## What a test looks like

One step, no ritual:

```python
def test_measure_reports_covered(trial: Trial) -> None:
    trial.shell.replies(when="mise run test:py:cov:diff*", exit_code=0)

    transition = trial.walk(measure, Uncovered(budget=3))

    assert transition == done(CoverReport(covered=True, remaining=3))
    assert trial.shell.commands == [
        "mise run test:py:cov:diff -- --fail-under 100"
    ]
```

A whole cast, over the path that is the reason `merge_ready` exists:

```python
def test_merge_ready_repairs_once_then_goes_green(trial: Trial) -> None:
    trial.shell.replies(when="mise run lint:py", exit_code=1, stdout="E501")
    trial.shell.replies(when="mise run test:py", exit_code=0, always=True)
    trial.shell.replies(when="mise run lint:py", exit_code=0)
    trial.decide.answers(answer=True, when="*hand it to the agent?*")
    trial.coding.replies("fixed the long line")

    result = trial.cast(merge_ready, MergeReady(bound=2))

    assert result == MergeReport(green=True, remaining=1)
    assert trial.steps == ["gates", "repair", "gates"]
    assert "E501" in trial.coding.prompts[0]
    assert trial.coding.calls[0].resume is None
```

`cast` and `walk` are synchronous — they own the loop, because a ritual test is
an ordinary test. `cast_async` and `walk_async` exist for a suite already
inside one, and calling the sync pair from a running loop raises saying so.

## The rituals file moves into `src/`

Tests without coverage would leave the same blind spot in a better disguise: a
suite can grow beside `rituals.py` for a year and nothing will say which of its
9 steps and 8 helpers no test has ever reached.

`[tool.coverage.run] source` takes packages and directories, not files, so a
root `rituals.py` cannot simply be named in it. What is left is widening the
source to `.` and omitting the rest of the repo, or `source_pkgs = ["rituals"]`,
which measures whatever `import rituals` resolves to and so depends on the cwd.
Moving the file is one line of config and no special case — `source = ["src"]`
picks it up because it picks up everything under `src`.

It also shortens `SRC_PATHS` in `mise.toml` from `src rituals.py` back to
`src`, and drops the paragraph of comment explaining the second entry. Every
tool the repo runs — mypy, ruff, black, pylint, vulture, coverage — stops being
told about this file twice.

Discovery survives on the config route, verified on a scratch project before
this was written:

```toml
# .vekna.toml, at the repo root
[rituals]
files = ["src/rituals.py"]
```

```console
$ vekna rituals list          # from the repo root
cover_diff  [--bound <int>]
...
$ cd src/sub && vekna rituals list   # and from anywhere below it
cover_diff  [--bound <int>]
```

`_config_files` walks up from the cwd, and `files` resolve **relative to the
config file**, so a cast started anywhere in the repo finds the same source.
`src` is already on `sys.path` — poetry's editable install writes a `vekna.pth`
holding exactly that path — so a test says `from rituals import merge_ready,
gates` and nothing new is configured to make it.

What it costs:

- **This repo stops exercising the implicit walk-up**, the default author
  experience and the thing `_find_rituals_file` exists for. It stays covered by
  `tests/integration/cli/`, which builds a `rituals.py` in a `tmp_path` — but
  not by daily use here.
- **The wheel must not gain a top-level `rituals` module.** poetry-core takes
  the package from the project name, so it builds `src/vekna` and nothing else,
  but `rituals` is a name an author is very likely to own. Checking the built
  wheel is an acceptance item rather than an assumption.
- **`0.5.0` inherits a slightly different move.**
  [10-ritual-modules.md](10-ritual-modules.md) turns this file into a `rituals/`
  package; from `src/` that package is reached by the `modules` route rather
  than the walk-up — precisely the route that doc puts the ritual root's parent
  on `sys.path` for. Nothing there is invalidated; one sentence in it is.
- **The stray `rituals/` at the repo root goes.** Untracked, holding nothing but
  a `__pycache__` from an earlier split experiment, and under
  `10-ritual-modules.md` a directory holding both `rituals.py` and `rituals/`
  becomes an error naming both.

Keep the move a pure rename in its own commit — git's rename detection is what
keeps diff-coverage from reading all 193 statements as changed lines the moment
the file lands in a measured directory.

## Scope

```text
src/vekna/trial/
  __init__.py   public: Trial, TrialScriptError, the recorded-call DTOs
  _pacts.py     recorded calls, the Script protocol, the errors
  _mills.py     scripts (match, queue, exhaust), the recorder, steps off events
  _links.py     the doubles — they sit where a Focus and a Channel sit
  _inits.py     Trial: installs the doubles, drives run_cast, holds the recorder

src/vekna/edges/pytest_plugin.py   the pytest11 plugin — one `trial` fixture
```

The plugin sits in the root `edges` rather than under `vekna/trial/`: pytest
loads an entry-point plugin before pytest-cov starts measuring, so a top-level
`vekna.trial` import there would report the whole lexicon as unexecuted.

- `lexicon/_pacts.py` — `ShellCall`, `ShellReply`, `ShellFocusProtocol`.
- `lexicon/_mills/engine.py` — `FocusSlot.resolve` taking a default, `.scope`
  installing and restoring.
- `lexicon/__init__.py` — the three shell types and `SHELL_FOCUS` exported.
- `folio/shell/_links.py` — `BashFocus` around `run_bash`; `shell()` resolving
  a Focus, defaulting to it.
- `pyproject.toml` — import-linter contracts for the new package (`vekna.trial`
  may import `vekna.lexicon` and the folios; **nothing may import
  `vekna.trial`**), the `trial` extra, the `pytest11` entry point.
- `rituals.py` → `src/rituals.py`, and a `.vekna.toml` at the repo root naming
  it. The stray untracked `rituals/` is deleted.
- `mise.toml` — `SRC_PATHS = "src"`, and the comment about the second entry
  goes with it.
- `tests/unit/trial/` — scripts, matching, exhaustion, the recorder.
- `tests/integration/trial/` — a cast end to end through the doubles, and the
  fixture under `pytester`.
- `tests/integration/rituals/test_{ritual}.py` — this repo's four.

**`vekna.trial` imports the lexicon's internals**, `Grimoire` and `run_cast`
among them, and gets a contract that says so — the reasoning is in
[`../architecture.md`](../architecture.md). If a third consumer appears, that is
when the second public door reopens.

**Both new sources are measured**: `src/vekna/trial/` and `src/rituals.py`
carry the usual 100% on changed lines. For the rituals that is the larger half
of the work — 193 statements across four rituals, nine steps and eight helpers,
none of it written with a test in mind. An awkward branch gets reached through
the doubles; `# pragma: no cover` is not the answer here, and neither is a
threshold that quietly excludes the file the release is about.

## Out of scope

- **Replay.** Driving a ritual from a recorded journal is
  [`../hand/05-replay.md`](../hand/05-replay.md) and needs the daemon's journal
  first. A trial scripts answers; a replay reads them back. Different feature,
  same shaped assertion at the end.
- **Generic interception by medium name.** An author's own medium gets its own
  seam, the way `coding` and `shell` have theirs. A by-name override in
  `@medium` would cover it in one mechanism and would short-circuit the medium
  body — the failure this design is arranged against. If enough author-written
  mediums appear to make it a pattern, it comes back as its own document.
- **Sandboxing a step body.** `trial` replaces mediums. A step that reaches for
  `subprocess` or `httpx` directly still does exactly that.
- **Migrating the existing suite.** `entry()` stays where the test is about the
  engine or a folio rather than about a ritual; `mock`-level tests of the
  coding medium keep mocking the SDK. What is not duplicated is `_cast` and
  `FakeFocus`, which the new package subsumes.
- **The daemon and the wire.** Nothing here observes a cast from outside the
  process.
- **Snapshot or golden-file assertions**, and any assertion helper beyond what
  `Goto`, `Done` and a list of names already give.

## Acceptance

- A ritual with `coding`, `shell` and `decide` calls runs to `done` under
  `trial.cast` with no subprocess started, no agent reached and no stdin read.
- `trial.walk(step, payload)` returns the step's `Transition` with no ritual
  declared, and refuses a payload of the wrong type the way a cast does.
- The two concurrent `shell` calls in `merge_ready.gates` are answered
  correctly whichever order they arrive in, 100 runs out of 100.
- A `coding` call declaring `session=Session.CONTINUE, key="repair"` shows up
  in `trial.coding.calls` with the first call's `session_id` as its `resume`.
- `coding(..., output=Judgement)` returns a validated `Judgement` from a
  scripted model, and a scripted reply that does not validate raises
  `CodingOutputError` — the medium's error, not the double's.
- An unscripted `shell` command raises `TrialScriptError` naming the command,
  and the cast stops there rather than defaulting to an exit code.
- A `decide` answer that is not one of the offered options raises before the
  ritual sees it.
- A trial that installed doubles leaves the focus registry exactly as it found
  it, including a focus the author registered before it ran.
- `shell()` in a process where nothing registered a Focus still runs bash —
  `tests/integration/folio/test_shell.py` passes unchanged.
- The four rituals in `src/rituals.py` each have a test over their happy path
  and at least one boundary: budget exhausted, gate red, human declines.
- `src/rituals.py` appears in the coverage report at 100%, and a subsequent
  change to a ritual that no test exercises fails `test:py:cov:diff
  --fail-under 100` — the gate `cover_diff` itself runs.
- `vekna rituals list`, `vekna rituals show` and `vekna cast` still find this
  repo's rituals from the repo root and from a subdirectory of it.
- The built wheel contains `vekna/` and no top-level `rituals` module.
- `mise run fullcheck` green, import-linter contracts included.
