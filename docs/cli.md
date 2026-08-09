# CLI reference

One binary, two command groups.

## `vekna cast`

Run a ritual.

```bash
vekna cast <ritual> [--<component> value ...]
```

Each of the ritual's component fields is an option. `--flag value` and
`--flag=value` are both accepted; a flag with no value is an error naming the
flag rather than swallowing the next one.

```bash
vekna cast fix_tests --bound 5
vekna cast review --base=main --only src/
```

Output streams live as a tree of rites. The last line is the result as JSON,
or `null` for a ritual that finishes without one.

Exit codes: `0` cast finished, `1` cast failed, `2` the arguments or the ritual
source were wrong.

### `vekna cast --prompt`

```bash
vekna cast --prompt "explain what this module does"
vekna cast -p "explain what this module does"
```

A one-shot cast on the `coding` medium, with no `rituals.py` needed. The
shortest way to check the agent is reachable at all.

### `vekna cast --help`

Lists the rituals it can find from here, each with its options. If the source
cannot be loaded, it says why rather than reporting an empty library.

## `vekna rituals`

Inspect the library without casting anything.

```bash
vekna rituals list          # every ritual and the options it takes
vekna rituals show <name>   # one ritual's components and its step graph
```

`show` draws the graph from the `goto` calls in each step's body:

```text
countdown
max steps: 100

components:
  --start <int>
  --label <str>  (optional)

steps:
  (start) → tick
  tick → tick, (done)
```

A `?` in place of a target means a `goto` naming a step the graph could not
find — usually a submodule that was never swept because it is missing an
`__init__.py`.

## `vekna`

With no subcommand, the daemon. The first `vekna` binds
`/tmp/vekna-<uid>.sock` and renders every cast running anywhere on this
account; each one after attaches to it as another surface, and sees the same
view.

```bash
vekna
vekna --debug
```

`--debug` writes a line per event to `~/.config/vekna/debug.log` — the daemon is
the one place every message passes, and the log says what it did with each one,
including the ones it dropped.

A number drills into a cast, `b` comes back, `q` quits. A cast blocked on a
prompt is marked as waiting, with the prompt — it is answered in the terminal
that started it, not here.

Casts are not started from here. `vekna cast` is how a cast begins, and it runs
in the directory it was typed in, attached or not.

## `vekna casts`

The casts the daemon has recorded, newest first — running, finished and gone.

```bash
vekna casts
```

A cast that ran with no daemon listening leaves no record: the journal is the
daemon's, and there was none.
