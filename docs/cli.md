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

Options before the ritual name are vekna's; everything after it belongs to the
ritual, `--`-prefixed or not. So a ritual is free to take a `--continue` of its
own, and vekna's never has to guess which was meant:

```bash
vekna cast --continue 6f1c2a9e     # vekna carries a cast on
vekna cast release --continue      # the release ritual's own flag
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

With no subcommand, the daemon. The first `vekna` binds
`$XDG_RUNTIME_DIR/vekna.sock` (falling back to `/tmp/vekna-<uid>/vekna.sock`,
in a directory of the user's own) and renders every cast running anywhere on this
account; each one after attaches to it as another surface, and sees the same
view.

Both ends have to compute the same path, and `XDG_RUNTIME_DIR` is what decides
it. A sandbox that cannot write to the session's runtime directory exports a
private one of its own instead — [fence](https://github.com/fencesandbox/fence)
does, and it deletes it again on the way out — so a cast started under one looks
for a socket in a directory nothing outside can name, and `vekna` in the shell
never sees that cast. Nothing is blocked: unix sockets cross a sandbox fine, the
two ends were simply dialing different paths. `VEKNA_SOCKET` is read before
`XDG_RUNTIME_DIR` and settles it, exported on both sides. This is a development
concern rather than an operating one — a cast belongs in the shell, where it is
the one running the agent — but a suite or a cast run from inside a sandbox will
otherwise look like it vanished.

```bash
vekna
vekna --debug
```

`--debug` writes a line per event to `~/.config/vekna/debug.log` — the daemon is
the one place every message passes, and the log says what it did with each one,
including the ones it dropped.

One row per cast, and no output in any of them — the row is for deciding which
cast to go and look at:

```text
vekna — 1 running · 1 waiting · 1 done · 1 aborted

  #  cast      ritual           project     status   elapsed  steps  now
  1  7c01ffab  triage           ludamus     waiting    1m03s      1  merge #74 now, or wait?
  2  3f9a2b11  merge_ready      vekna       running    4m12s      3  land · coding  1m02s
  3  dd44ee55  ping             deep        done          7s      1
  4  91bb0c4d  fix_demo         vekna       aborted   10m09s      7  vekna cast --continue 91bb0c4d
```

`elapsed` is how long the cast has been going, `steps` how many it has
finished, and `now` what it is doing this second — the running step, the medium
inside it, and how long that step has been running. A step that has not moved
in ten minutes is the thing this view exists to show. Casts waiting on an
answer sort to the top, then the ones still running, then the ones that ended.

The status word is `running`, `waiting`, `done`, `failed` or `aborted` —
aborted being a cast whose socket closed without a goodbye, which is the one
worth carrying on with, so its row prints the command that does it.

A number drills into a cast, `b` comes back, `q` quits. Drilling in is where
the rite tree, the live output and the error a failed cast ended on are. A cast
blocked on a prompt is answered in the terminal that started it, not here.

Casts are not started from here. `vekna cast` is how a cast begins, and it runs
in the directory it was typed in, attached or not.

## `vekna log`

The casts the daemon has recorded, newest first — running, finished and gone.

```bash
vekna log
```

A cast that ran with no daemon listening leaves no record: the journal is the
daemon's, and there was none.

### `vekna cast --continue`

Runs a cast on from where it was interrupted, in the directory it ran in.

```bash
vekna cast --continue 6f1c2a9e
```

A fresh process, always. It re-runs the ritual's steps — cheap, and the same
walk it took before — while every agent call, shell command and prompt it had
already finished comes back off the journal instead of happening twice. An
agent rite that was interrupted mid-flight runs again, on the session the cast
had already opened, so it remembers what it was told.

Replay stops at the first rite that does not match what was recorded, and the
cast runs live from there. A ritual that takes a different path this time is
not made to pretend otherwise.
