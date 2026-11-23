---
description: "vekna CLI reference: vekna cast, rituals, the dashboard window, resuming a cast with --continue, unattended casts, notifications, log and stop."
---

# CLI reference

One binary, two command groups.

/// html | div.diagram
    markdown: html

--8<-- "cast.svg"
///

## `vekna cast`

Run a ritual.

```bash
vekna cast <ritual> [--<component> value ...]
```

Each of the ritual's component fields is an option. `--flag value` and
`--flag=value` are both accepted; a flag with no value is an error naming the
flag rather than swallowing the next one. A flag the ritual does not take is
refused, with the list of those it does.

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

At a terminal those are one line when nothing printed in between: the `↳` turns
into `✓`, `✗` or `⊘` where it stands. A rite that printed, or that something else
printed after, closes on its own line as above. Output sent to a file or a pipe
always keeps both lines and carries no cursor codes.

A shell command that exits non-zero ends in `✗` with its code, as in
`✗ shell  make check  — exit 2`. The mark reports the call; the ritual still
reads the exit code and decides, so the cast carries on, and a resumed cast
takes the result off the journal rather than running the command again.

The last line is the result as JSON, or `null` for a ritual that finishes
without one.

Exit codes: `0` cast finished, `1` cast failed, `2` the arguments or the ritual
source were wrong, or a medium the ritual calls has no focus registered.

### Following what it queued

A cast typed with a daemon running stays at its terminal for as long as the
casts it queued — and the ones they queued — are still going. They run one at a
time, the typed cast among them, so the terminal is one stream that reads in
order and scrolls back like any other output. A cast that awaits another waits
while that one runs, then carries on before the next one starts.

A cast's lines are printed as it writes them. A line names the cast where it
takes over from another:

```text
▶ fan_out
✓ fan_out
result: {"queued":[...]}
── ci_watch 3f9a2b11 ──
▶ watch
  ✓ shell  gh pr checks 412
── pr_fix 91bb0c4d ──
▶ repair_ci
✓ repair_ci
[pr_fix 91bb0c4d] ✓ done
── ci_watch 3f9a2b11 ──
✓ watch
[ci_watch 3f9a2b11] ✓ done
```

A prompt from any of them is asked here, under what its cast printed last,
with the cast's name in front. A prompt taken over in `vekna` stops being asked
here, and is asked again if that window lets it go or closes. A prompt this
terminal cannot answer — the cast is `--unattended`, or input has ended — is
said in a line and holds nothing:

```text
[pr_fix 91bb0c4d] ⏸ push? — answer it in `vekna`
```

Output to a pipe or a file reads the same.

The cast exits `1` if any of them failed. Ctrl-C stops following and leaves
them running; `--no-follow` ends the cast with its own steps. Either way they
still run one at a time:

```bash
vekna cast --no-follow sweep
```

### `vekna cast --queue`

```bash
vekna cast --queue sweep --max-prs 5
```

Hands the ritual to the daemon and returns, starting the daemon if none is
running. The cast runs there with no terminal, the casts it queues run side by
side up to `[circle] processes` and `total_processes`, and `vekna` shows them
and answers their prompts. This is what `c` in the window does.

The ritual's name and components are checked before the daemon is asked, so a
mistake is said at once and exits `2`. Otherwise the command prints the queued
cast's id and exits `0`:

```text
queued sweep 6f1c2a9e — `vekna` shows it
```

`--queue` takes a ritual: it does not go with `--prompt`, `--continue`,
`--unattended` or `--no-follow`.

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

A step can also ask first: `attended()` from `vekna.lexicon` is false under the
flag, so a ritual can skip the work a question would have approved and say so.
A cast carried on with `--continue` stays unattended whether or not the flag
is typed again, and the flag on `--continue` makes an attended cast
unattended. A cast it queues is unattended too.

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

## `vekna audit`

Check the config that speaks for the directory you are in, without casting
anything.

```bash
vekna audit
```

It reads your user config and the project's `.vekna.toml`, and prints three
things: each setting with the layer it is taken from, what is wrong, and what
sets nothing.

```text
layers, nearest first:
  1  /home/me/app/.vekna.toml
  2  /home/me/.config/vekna/config.toml: [projects.app]
  3  /home/me/.config/vekna/config.toml

[rituals]
  modules cabinet = cabinet.rituals  ← 1, 3
[circle]
  processes = 4  ← 2 (over 3: 2)
[defaults.sweep]
  base_branch = "main"  ← 1

errors:
  /home/me/app/.vekna.toml: [defaults.sweep] sets 'branch', which sweep does not take

pointless:
  /home/me/.config/vekna/config.toml: [projects.old] path = '~/old' does not exist
```

`← 2 (over 3: 2)` reads: layer 2 sets the value, over the `2` that layer 3
says. A layer that says the same value is left out. `[rituals]` lists every
layer that names a source, because each layer adds to that table.

**errors** are what a cast or the daemon would refuse or ignore: a file that
does not parse, a key a table does not take, a tome that does not import, a
`[defaults.<ritual>]` value the ritual refuses. Any error makes the exit
code 1.

**pointless** lists settings that change nothing here, and leaves the exit
code alone:

- a `[projects.<name>]` table whose `path` does not exist
- a key in your `[projects.<name>]` table that the project's `.vekna.toml`
  also sets, or that equals the value it overrides
- `[circle] coding`, `total_processes` or `vigil_processes` anywhere but the
  top level of your user config
- a `[defaults.<ritual>]` table for a ritual that is not loaded here, unless
  it is in the top level of your user config, which speaks for every project
- a table that vekna does not read and that no tome in `[rituals] modules` is
  named after. Another tool may read it, so check before you delete it.

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

In a terminal the window is drawn with Textual, as two pages of a book. The left
page is the contents: a tree of project, ritual, the ritual's casts newest first
(`@now` while live; once ended, the slot it began in: `@<1h`, `@<3h`, `@<6h`,
`@<12h`, `@<1d`, then `@2d ago`), and their rites. This is the tree
view: every cast that is live, and every cast that ended less than a day ago.

A ritual line holds the casts that still run or ask. A cast that ended moves
under the project's `finished` line, which lists every ended cast by ritual. A
cast that ended like the cast before it, of the same ritual and arguments, is
not drawn: the newest one stands for the streak and says how long it is, `x8`.
Two casts ended alike when their status, their result and their error are the
same. A cast that another cast queued hangs under that cast and says its ritual;
where casts of one ritual differ by an argument, each says which: `--number 347`.

When the window opens, it folds the tree once to fit its height, and keeps as
much as fits: every running cast open to its whole rite tree; then `finished`
folded too; then the running casts back to one line; then every project where
nothing runs folded as well. After that the folds are yours.

A cast is one line; a running one also
shows `…` and the rite it is on now, or the rite that asks. `space` on a cast
opens its whole rite tree, and `space` again closes it. The right page is the
line under the cursor in full: a project's branch and directory, a ritual's
casts with their flags, a cast's whole rite tree, or a rite's whole error. Below
it is the output, which follows the newest line until you scroll up. The branch
is read off git every few seconds, because a cast can switch it.

On any other line `space` folds: the fold hides everything under the line, and
the line says what happens there: `▸ ci_watch (1 asks, 1 fail, 2 running)`. A
project line always says it. `f` folds every project, ritual and `finished`
line at once; when they are all folded, `f` opens them all again.

`H` turns the left page to the history view, and `H` again turns it back. While
no cast is old enough for it, `H` stays in the tree view and says so. The
history view holds the casts that ended a day ago or more, grouped by the day
they ended, newest first, each with the time it ended and its ritual. The hint
line says how many it holds: `H history (12)`. Both views
show what the daemon has held since it started; `vekna log` has the rest.

How long a cast stays in the tree view after it ends is `history_after`, an
[ISO 8601 duration](https://en.wikipedia.org/wiki/ISO_8601#Durations), in the
project's `.vekna.toml` or in `~/.config/vekna/config.toml`, the
[nearest that sets it](scopes.md#which-setting-wins):

```toml
[window]
history_after = "P1D"   # the default; "PT12H", "PT30M", "PT0S" for at once
```

A value that does not read is named in the window's note line and passed over.

| Key | Does |
| --- | --- |
| `H` | the history view, or the tree view again |
| `space` | on a cast, open its whole rite tree or close it; elsewhere, fold the line or open it again |
| `f` | fold every line that holds casts, or open them all again |
| `w` | the next line that asks, a fold included |
| `j` / `k` / `h` | down, up, to the line above in the tree |
| `c` | start a ritual here: `c <ritual> [--flag value …]` |
| `t` | take over the running cast under the cursor, or the first one that asks under a fold |
| `a` | answer it in one line: `a <answer>` |
| `x` | cancel the cast under the cursor; twice, to be sure |
| `:` | the command line, empty |
| `g` / `p` | every project / this one |
| `q` | close the window; the daemon keeps running |

A cast that waits on you is one line on top, naming the cast. Take it over to
read the question. The left page then opens the cast's whole rite tree, and
the right page is its output. Every prompt it asks is claimed and shown at the
end of that output, and the line under the output answers it on Enter. The
contents take no keys meanwhile, and a prompt from another cast shows as one
line under them. Esc leaves and hands the open prompts back to whoever was
answering them. The takeover also ends when the cast does, and when the cast
asks nothing for five seconds after an answer. It covers that one
cast: a cast it queued is taken over on its own.
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
or in `~/.config/vekna/config.toml`, where a `[projects.<name>.circle]` table
sets it for [one project](scopes.md#one-config-for-every-project):

```toml
[circle]
processes = 4         # casts running at once in this project; the nearest table wins
total_processes = 8   # casts running at once, across every project; user config only
coding = 2            # agent sessions at once, across every project; user config only
vigil_processes = 7   # casts started by vigils at once; user config only
```

`processes` counts every running cast of the project, whether `c` started it or
somebody typed `vekna cast`; past it, `c` queues. It defaults to 4.
`total_processes` counts every running cast of every project the same way, and
defaults to the number of processors. With either limit reached, a cast asked
for with `c` or `vekna cast --queue` waits queued, and a cast typed as plain
`vekna cast` is refused before its first step, with exit code `1`:

```text
8 of 8 casts are running on this machine: queue it with `vekna cast --queue sweep`, or wait for one to end
```

`coding`
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

### Vigils

A vigil casts a ritual every so often, with nobody typing it. It is a ritual,
an interval in seconds, and optional arguments for the ritual:

```toml
[vigil.prwatch]
every = 3600
ritual = "heal.mine"
args = { author = "me" }
```

A `[vigil.<name>]` table at the top level of your user config runs in every
project that has a `[projects.<name>]` table whose `path` exists. A
`[projects.<name>.vigil.<name>]` table, or the `.vekna.toml` of a listed
project, sets a vigil for that one project. The nearest table replaces a
farther table of the same name whole: no key is merged. A project cannot turn
a top-level vigil off, only replace it.

`ritual` is the name as you type it after `vekna cast`: bare, or with its
tome, `cabinet:heal.mine`. A bare name counts a cast of that name from any
tome. `args` set the ritual's components as flags typed after its name do, and
override `[defaults.<ritual>]` the same way.

A vigil is due when `every` seconds have passed since a cast of that ritual
last started in that project, whoever started it. A vigil that has never run is
due at once. The daemon looks every five seconds, so no interval is kept more
closely than that. A due vigil starts a cast only when all three hold:

- no cast of that ritual is queued or running in the project, a cast typed by
  hand included
- the project and the machine each have a slot that no queued cast is waiting
  for
- fewer than `[circle] vigil_processes` casts started by vigils are queued or
  running

Otherwise it stays due, and the daemon tries it again on the next look. When
several are due, the longest overdue goes first. However many intervals passed
while the daemon was down, a vigil casts once.

`vigil_processes` defaults to one less than `total_processes`, and to 1 at
least. A cast that a vigil's cast queues or awaits does not count toward it. A
cast names the vigil that started it in the drilled view: `vigil prwatch`.

The daemon reads the config again on every look, so an edit counts without a
restart. A `[vigil]` that does not validate is noted in `daemon.log` and left
out; `vekna audit` names it.

Three limits to know:

- The interval is counted from the journal, which keeps the newest 200 casts
  and is trimmed when the daemon starts. A vigil whose last cast was trimmed is
  due at once after a restart.
- A ritual that needs a worktree waits queued when no tree is free, and counts
  toward `vigil_processes` while it waits.
- For a few seconds after a restart, the daemon does not see a cast typed by
  hand that is still running, and a due vigil can start a second one.

### Worktrees

A ritual declared `@ritual("fix", worktree=True)` runs in a pooled worktree
rather than in the directory `c` was typed in. The daemon leases a tree before
it spawns the cast and releases it once the process exits. The pool takes
three more keys:

```toml
[circle]
worktrees = 2                          # pooled trees per project
prepare = "mise install && poetry install"   # run in each tree when it is set up
base_branch = "main"                   # what each tree is made on and fixed to
```

Trees live under `~/.local/state/vekna/worktrees/<repo>-<hash>/<n>`, each parked
on its own branch, `vekna/wt-<n>`, while no cast holds it. The pool is whatever
`git worktree list` shows there, so a restarted daemon finds the same trees.

[`vekna altar init`](#vekna-altar) makes the pool, and nothing else does. A
lease hands out only a tree the altar set up, so `prepare` runs before any
ritual and never inside a cast. With no tree set up, a `worktree=True` cast
fails and says `run vekna altar init`. A ritual that asks for no worktree needs
no pool.

After the cast, the daemon parks a clean tree. A tree with uncommitted or
untracked changes, or with a merge, rebase, cherry-pick or revert in progress,
is left as it is and marked blocked: the cast's drilled view and `daemon.log`
say which tree and why. It joins the pool again once it is clean, by hand or
through [`vekna altar fix`](#vekna-altar). Gitignored
files are not changes, so whatever `prepare` builds must be gitignored, or
every tree reads dirty. Past the pool, a cast waits queued for a tree while
another cast holds one; once every tree is blocked and none is held, nothing
would free one, so the cast fails and names the blocked trees. A cast also fails
when every tree that is not blocked belongs to a cast awaiting one that waits
for a tree: neither would ever end.

A tree holds only what git tracks. A `.vekna.toml` or `rituals.py` kept out of
git is not there, and a cast in the tree will not find its rituals. A
`worktree=True` ritual typed as `vekna cast` runs where it was typed.

## `vekna altar`

Tends the pooled worktrees of the project it is typed in. Bare `vekna altar`
lists its subcommands.

| Command | Trees | What it does |
| --- | --- | --- |
| `vekna altar list` | all | says how each tree stands; changes nothing |
| `vekna altar init` | missing ones, up to `worktrees` | makes each on the base and runs `prepare` in each tree not set up yet |
| `vekna altar fix [TREE] [--save]` | every tree no cast holds | aborts an open merge, rebase, cherry-pick or revert, throws away uncommitted and untracked changes, parks the tree, moves its parking branch to the base and runs `prepare` again |
| `vekna altar reset [TREE] [--save]` | every tree no cast holds | removes the tree from git and from disk, with its marker and log, then makes it again as `init` does |

`TREE` is a tree's number, the last part of its path. With it, `fix` and
`reset` act on that tree alone, and fail when a running cast holds it. Without
it, a held tree is left alone and said so.

The base is `[circle] base_branch`, or the `HEAD` of the checkout the command
is typed in when the key is unset. Nothing is fetched: a stale local branch
gives stale trees.

`prepare` runs with the tree as its directory and logs to `<n>.prepare.log`
beside it. A tree is set up once `<n>.prepared` stands beside it; a `prepare`
that fails leaves no marker, so no cast is handed the tree, and the next
`init` runs it again. `fix` keeps gitignored files, so a prepared venv is
reused; `reset` removes them with the tree. While the altar works, worktree
casts of the project wait.

```bash
vekna altar list            # how each tree stands
vekna altar init            # once per project, and after raising `worktrees`
vekna altar fix             # throws away what the trees had not committed
vekna altar fix 2 --save    # tree 2 only, its work committed to a branch first
vekna altar reset           # every tree removed and made again
```

```text
/home/you/.local/state/vekna/worktrees/vekna-1a2b3c4d/1: ready — its uncommitted work is on vekna/rescue/fix-flaky-1f2e3d4c
/home/you/.local/state/vekna/worktrees/vekna-1a2b3c4d/2: held by a running cast, left alone
```

Each line is one tree: `ready`, `removed`, `held by a running cast, left
alone`, `blocked: <why no cast can take it>` from `list`, or `failed: <why>`.
`--save` names each branch `vekna/rescue/<branch the tree was on>-<hash>`, and
keeps it local. The daemon does the work, since only it knows which trees are
held; with none listening, `vekna altar` starts one. A cast whose tree is
parked again or removed loses its blocked mark in every window. Exits `1` when
any tree failed.

## `vekna stop`

Ends the daemon, and every window on it with it. Casts still running carry on,
and rejoin the next daemon with everything they have done so far.

```bash
vekna stop
```

Prints `stopped the daemon` once the socket stops answering, so `vekna stop &&
vekna` starts a fresh one. With nothing listening, `no daemon running`; both
exit `0`.

## `vekna version`

Prints this vekna's version, then the version of the daemon on the socket. It
starts no daemon and is never refused.

```bash
vekna version
```

```text
vekna 3.0.0
daemon 3.0.0 on /run/user/1000/vekna.sock
```

With nothing listening the second line is `daemon: not running`. A daemon that
predates this command cannot say its version, and the line says so. The window
shows the same versions at the right of its hint line.

### Compatibility

A daemon serves its own major version only. Every `vekna`, `vekna cast` and
`vekna altar` asks the daemon for its version first. When the major versions
differ, or the daemon cannot say its version, the command stops before it sends
anything else and prints both ways out:

- `vekna stop` ends that daemon, and the next `vekna` starts this version's.
- `VEKNA_SOCKET` and `VEKNA_STATE`, exported for every vekna that should use
  it, give this version a daemon beside the other. `VEKNA_STATE` moves the
  journal, the logs and the worktree pool, which two daemons must not share.

A cast already running stays away from a daemon of another major version that
starts under it, and carries on unwatched.

No minor or patch release may break this: within one major version, any vekna
talks to any daemon.

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

With a cast id, or the eight characters of one, it shows that cast: its rites
with their errors, why the cast ended, and the output of each rite that did not
end `ok` (the last 200 lines of it).

```bash
vekna log 91bb0c4d
```

```text
vekna — fix_demo  /home/you/vekna  failed  2m10s  91bb0c4d

 ✓ measure
 ✗ repair  — exit 2

 repair: exit 2

── repair (error) ──
FAILED tests/test_demo.py::test_it - AssertionError
```

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
