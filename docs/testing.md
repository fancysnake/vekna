# Testing rituals

A ritual is a program, and it deserves the same test any other program gets.
`vekna.trial` runs one with every medium answering from a script, so a test
costs no agent call and no wall time.

```bash
pip install vekna[trial]
```

That brings a `trial` pytest fixture.

## One step

`trial.walk(step, payload)` runs a single step and hands back its transition.
No ritual required — this is the unit of a step test.

```python
def test_a_green_run_finishes(trial):
    trial.shell.replies(exit_code=0)

    transition = trial.walk(fix, Attempt(left=3))

    assert transition.result.outcome == "green"
    assert trial.shell.commands == ["pytest"]
```

## A whole cast

`trial.cast(ritual, components)` runs the ritual across steps and returns the
result model.

```python
def test_it_gives_up_after_the_budget(trial):
    trial.shell.replies(exit_code=1, always=True)
    trial.coding.replies("tried something", always=True)

    result = trial.cast(fix_tests, FixTests(bound=2))

    assert result.outcome == "gave up"
    assert len(trial.coding.prompts) == 2
```

## Scripting the answers

Each double takes answers matched by a glob — the command for `shell`, the
prompt for `coding` and `decide` — and falls back to an ordered queue for
whatever no pattern claims:

```python
trial.shell.replies(when="mise run lint*", exit_code=0)
trial.coding.replies("wrote a test", uses=["Bash"])
trial.decide.answers(answer=True, when="*proceed*")
```

`always=True` keeps one answer standing instead of consuming it.

**Nothing defaults.** An unscripted call raises `TrialScriptError` naming the
call and what the script still held. An invented `exit_code=0` would send the
ritual down a branch nobody wrote and report the run as a pass, which is worse
than no test at all.

## Assert on what the doubles recorded

`trial.shell.commands`, `trial.coding.prompts`, `trial.coding.gated`,
`trial.decide.prompts`. There is no `assert_called_with` here — the recording
is the assertion surface.

## What the doubles do not replace

The doubles stand at the folio's *outer* edge, where a medium reaches the
outside world, so the medium's own body still runs: session threading, `resume`
resolution, output-schema validation and exit-code handling are all exercised.

A ritual that mis-declares `session=Session.CONTINUE` fails its test. That is
the point of doubling at the edge rather than mocking the medium.

## Two things that will catch you out

- **A tool gate arrives at `trial.decide`, not at `trial.coding`.** The folio
  builds both out of the same channel, so `allow tool 'Bash'?` is a decide.
- **A `Trial` answers only inside its `with` block.** The fixture hands you one
  already entered. Outside it, `cast` and `walk` raise `TrialError` rather than
  letting `shell()` fall through to real bash — a test that forgot the block
  would otherwise run its commands for real and pass.

Two mediums started in one `asyncio.TaskGroup` arrive in whichever order the
scheduler picks, which is what the ordered queue is for. An exception from
inside a group arrives wrapped, so a test reaching a grouped step needs
`pytest.raises(BaseExceptionGroup)` and an assertion on `.exceptions[0]`. That
is Python's doing, not the trial's.

`trial.cast_async` and `trial.walk_async` are for a suite already inside an
event loop; the plain forms own one.
