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

### Following what it queued

A cast typed with a daemon running stays at its terminal once its own steps
end, for as long as the casts it queued — and the ones they queued — are still
going. Each one's rites stream under its name:

```text
✓ fan_out
result: {"queued":[…]}
following the casts this one queued — Ctrl-C leaves them running
[ci_watch 3f9a2b11] ▶ watch
[ci_watch 3f9a2b11] ✓ watch
[pr_fix 91bb0c4d] ▶ repair_ci
[pr_fix 91bb0c4d] ✓ done
[ci_watch 3f9a2b11] ✓ done
```

Their prompts are asked here, one at a time, under the same name. A prompt
taken over in `vekna` stops being asked here, and is asked again if that window
lets it go or closes. The cast exits `1` if any of them failed. Ctrl-C stops
following and leaves them running; `--no-follow` ends the cast with its own
steps:

```bash
vekna cast --no-follow sweep
```

### `vekna cast --prompt`

```bash
vekna cast --prompt "explain what this module does"
vekna cast -p "explain what this module does"
```

A one-shot cast on the `coding` medium, with no `rituals.py` needed. The
shortest way to check the agent is reachable at all.

### `vekna cast --unattended`

```bash
vekna cast --unattended nightly_triage
```

For a cast nobody watches. Every `decide` fails where it is asked with
`UnattendedPromptError`, naming the question, instead of waiting on a terminal
nobody reads. The error raises inside the step, so a ritual can route it to a
recovery step (see [Rituals](rituals.md#when-a-step-fails)). Without the flag
nothing changes.

### `vekna cast --help`

Lists the rituals it can find from here, each with its options. If the source
cannot be loaded, it says why rather than reporting an empty library.

## `vekna rituals`

Inspect the library without casting anything.

```bash
vekna rituals list          # every ritual and the options it takes
vekna rituals show <name>   # one ritual's components and its step graph
```

`show` draws the graph from each step's return annotation — the exits mypy
checked:

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

An exit no step takes is refused as the library loads, so `list`, `show` and
`cast` all stop with `<step> may return <Class>, which no step takes` — usually
a submodule that was never swept because it is missing an `__init__.py`.

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

With no subcommand, the dashboard of the project it was typed in. The first
`vekna` starts the daemon, detached: it binds `$XDG_RUNTIME_DIR/vekna.sock`
(mode `0600`, falling back to `/tmp/vekna-<uid>/vekna.sock`, in a directory of
the user's own), writes what it has to say to `~/.local/state/vekna/daemon.log`,
and keeps running when the window closes. Every `vekna`, the first one too, is
a surface on it, and `q` closes only the window. `vekna stop` ends the daemon.

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
vekna --no-tui
```

`--debug` starts the daemon writing a line per event to
`~/.local/state/vekna/debug.log` — the daemon is the one place every message
passes, and the log says what it did with each one, including the ones it
dropped. A daemon already running is not restarted for it; the window says so.

In a terminal the window is drawn with Textual: a table of casts, and the one
under the cursor in a pane beside it — its rite tree, the output of what is
running, its branch and the directory it runs in, which for a pooled tree is
the tree. The table's `branch` and `where` columns say the same per cast; the
branch is read off git every few seconds, because a cast can switch it.

| Key | Does |
| --- | --- |
| `c` | start a ritual here: `c <ritual> [--flag value …]` |
| `t` | take over the prompt of the cast under the cursor, and answer it in a dialog |
| `a` | answer it in one line: `a <answer>` |
| `g` / `p` | every project / this one |
| `q` | close the window; the daemon keeps running |

Esc in the dialog lets the prompt go, back to whoever was answering it.
`--no-tui`, or no terminal on stdin and stdout, gives the line view described
below, which repaints whole and reads a line at a time.

A project is a repository, not a directory: every worktree of one shares its git
common dir, and its casts group under that. A directory in no repository is its
own project. `g` shows every project's casts, read only; `p` comes back to this
one.

One row per cast, and no output in any of them — the row is for deciding which
cast to go and look at:

```text
vekna — 1 running · 1 waiting · 1 done · 1 aborted  (all projects)

  #  cast      ritual           project     status      elapsed  steps  now
  1  7c01ffab  triage           ludamus     waiting       1m03s      1  merge #74 now, or wait?
  2  3f9a2b11  merge_ready      vekna       running       4m12s      3  land · coding  1m02s
  3  dd44ee55  ping             deep        done             7s      1
  4  91bb0c4d  fix_demo         vekna       aborted      10m09s      7  vekna cast --continue 91bb0c4d
```

`elapsed` is how long the cast has been going, `steps` how many it has
finished, and `now` what it is doing this second — the running step, the medium
inside it, and how long that step has been running. A step that has not moved
in ten minutes is the thing this view exists to show. Casts waiting on an
answer sort to the top, then the ones still running, then the ones that ended.

The status word is `running`, `waiting`, `recovering`, `queued`, `done`,
`failed` or `aborted`. Queued is a cast the daemon has not started yet, because
its project already runs as many casts as it allows. Recovering is a running
cast whose last step raised and went to a recovery step; drilling in shows the
error beside the step. Aborted is a cast whose socket closed without a goodbye,
which is the one worth carrying on with, so its row prints the command that does
it.

A number drills into a cast, `b` comes back, `g` and `p` switch between every
project and this one, `q` closes the window. Drilling in is where
the rite tree, the live output and the error a failed cast ended on are.

`c <ritual> [--<component> value …]` starts a ritual in the directory the window
was opened in, with the flags `vekna cast` takes. The daemon spawns it as `vekna
cast` with no terminal, logging its output to `cast.log` beside its record. A
ritual that is not there, or a component that will not validate, shows as that
cast failing, with the reason in its drilled view.

A cast the daemon started has no terminal, so its prompts are answered here:
drill into it and type `a <answer>`. The prompt line says what it takes —
`a yes|no`, the options offered, or `a <anything>` for free text. An answer it
does not offer is refused before it leaves the window. A cast nobody answers
waits. A cast typed as `vekna cast` asks its own prompts on its own terminal,
and the ones of the casts it queued; answering one from a window takes it over,
and that terminal stops taking answers for it. Only one answer ever counts: a
prompt taken over answers only to the window that took it, until that window
lets it go or closes.

`vekna cast` still runs in the directory it was typed in, attached or not. It
does not start a daemon: with none listening it runs on its own and joins the
next one that starts.

### The circle

How much runs at once is set under `[circle]`, in the project's `.vekna.toml`
or in `~/.config/vekna/config.toml`:

```toml
[circle]
processes = 4   # casts running at once in this project; the project's own wins
coding = 2      # agent sessions at once, across every project; user config only
```

`processes` counts every running cast of the project, whether `c` started it or
somebody typed `vekna cast`; past it, `c` queues. It defaults to 4. `coding`
limits how many `coding` calls talk to an agent at once, in every cast attached
to the daemon: past it, a call waits for a slot before its session starts, and
gives it back when the session ends. It defaults to no limit. With no daemon
running there is nobody to share with, and nothing waits. Both are read again
for every cast, so an edit counts from the next one. A `[circle]` that does not
validate is noted in `daemon.log`, and the defaults stand.

A cast that a ritual's `await_cast` blocks shows `on child` and the id it waits
on, and holds no slot until that cast ends. A cast queued by another names it
in the drilled view: `queued by <id>`. What is queued survives `vekna stop`:
the next daemon runs it.

### Worktrees

A ritual declared `@ritual("fix", worktree=True)` runs in a pooled worktree
rather than in the directory `c` was typed in. The daemon leases a tree before
it spawns the cast and releases it once the process exits. The pool takes two
more keys:

```toml
[circle]
worktrees = 2                          # pooled trees per project
prepare = "mise install && poetry install"   # run once in each new tree
```

Trees live under `~/.local/state/vekna/worktrees/<repo>-<hash>/<n>`, each parked
on its own branch, `vekna/wt-<n>`, while no cast holds it. The pool is whatever
`git worktree list` shows there, so a restarted daemon finds the same trees. A
tree is made when every existing one is held and the pool is under
`worktrees` (default 2), from the `HEAD` of the tree the cast was asked from;
`prepare` runs once in it, logging to `<n>.prepare.log` beside it. A prepare
that fails fails the cast
and runs again at the tree's next lease. Nothing removes a tree.

After the cast, the daemon parks a clean tree. A tree with uncommitted or
untracked changes, or with a merge, rebase, cherry-pick or revert in progress,
is left as it is and marked blocked: the cast's drilled view and `daemon.log`
say which tree and why. It joins the pool again once it is clean. Gitignored
files are not changes, so whatever `prepare` builds must be gitignored, or
every tree reads dirty. Past the pool, a cast waits queued for a tree while
another cast holds one; once every tree is blocked and none is held, nothing
would free one, so the cast fails and names the blocked trees. A cast also fails
when every tree that is not blocked belongs to a cast awaiting one that waits
for a tree: neither would ever end.

A tree holds only what git tracks. A `.vekna.toml` or `rituals.py` kept out of
git is not there, and a cast in the tree will not find its rituals. A
`worktree=True` ritual typed as `vekna cast` runs where it was typed.

## `vekna stop`

Ends the daemon, and every window on it with it. Casts still running carry on,
and rejoin the next daemon with everything they have done so far.

```bash
vekna stop
```

Prints `stopped the daemon` once the socket stops answering, so `vekna stop &&
vekna` starts a fresh one. With nothing listening, `no daemon running`; both
exit `0`.

## `vekna log`

The casts the daemon has recorded, newest first — running, finished and gone.

```bash
vekna log
```

```text
91bb0c4d  ✗  fix_demo          2026-08-21 14:02  /home/you/vekna
7c01ffab  ▶  triage            2026-08-21 13:58  /home/you/ludamus
3f9a2b11  ✓  merge_ready       2026-08-21 13:40  /home/you/vekna  ↳ 91bb0c4d
6f1c2a9e  ✗  cover_diff        2026-08-21 13:12  /home/you/vekna  ◌ gap
a1b2c3d4  ?  damaged           2026-08-21 12:50
```

The id is cut to eight characters, the timestamp is in your own zone, and a
trailing `↳` names the cast this one was carried on from. A cast that ran with
no daemon listening leaves no record: the journal is the daemon's, and there was
none.

`◌ gap` is a run whose log the daemon could not finish writing. It is still
resumable; what it lost is the tail.

`damaged` is a run whose `run.json` is missing or cannot be read — a daemon
killed inside a write, a disk that lost the file. The id is the directory's
name and the time is the directory's; nothing else is known, and
`vekna cast --continue` refuses it — saying the run is damaged, not that the
journal never saw it.

The journal itself is `~/.local/state/vekna/runs/<cast_id>/` — `run.json` for
what the cast was and how it ended, `events.jsonl` for the wire verbatim. The
root is trimmed to the newest 200 casts at startup; whatever is still running
is spared, and a damaged run is collected like a finished one.

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

The id may be the eight characters `vekna log` and the aborted row print — a
prefix is resolved against the journal, and one naming two casts is refused
rather than guessed. What comes back is a cast of its own, with an id of its
own; `vekna log` and the drilled-in header both say which cast it carries on
from.

A run the daemon could not write in full is resumed like any other. The log
never grows past a write it lost, so what a gap costs is the tail — the same
thing an interrupted cast loses — and the replay stops there and runs live from
there.
