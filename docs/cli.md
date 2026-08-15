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

Output streams live as a tree of rites — one node per step, one nested under it
per medium call, with the call's own output indented beneath:

```text
▶ gates
  ↳ shell  mise run lint:py
  ↳ shell  echo hi; sleep 1; echo bye
    All checks passed!
  ✓ shell  mise run lint:py
    hi
    bye
  ✓ shell  echo hi; sleep 1; echo bye
✓ gates
result: {"green":true}
```

A medium's line quotes the first string it was called with — a `shell`'s
command, a `coding` prompt — on one line, cut to 60 characters. Two rites of
the same medium are told apart by that, so it rides both the opening and the
closing line.

The last line is the result as JSON, or `null` for a ritual that finishes
without one.

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

With no subcommand, prints the help.
