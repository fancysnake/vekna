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

A medium's line quotes its first argument when that is a string, whitespace
collapsed and cut to 60 characters, on the line that opens the rite and the one
that closes it.

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

## Notifications

A cast that stops for an answer, or that ends, raises a desktop notification —
OSC 777, which Ghostty, kitty, wezterm and foot turn into an OSD. A terminal
that does not know the sequence drops it, and a redirected cast never sees one:
notifications go to a tty and nowhere else.

Three kinds:

- `decide` — a question waiting on you: the `decide` medium's own, coding's
  tool gate, or the agent asking mid-rite.
- `done` — the cast finished.
- `failed` — the cast failed, with the error in the body.

## `vekna`

With no subcommand, prints the help.
