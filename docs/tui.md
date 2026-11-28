---
description: "vekna window manual: read the cast tree, answer a waiting cast, take a cast over, open a failed rite, fold, history, start and cancel casts."
---

# The window

`vekna` with no subcommand opens the window on the project you typed it in.
This page walks through what you do there, one screen at a time.
[CLI reference § `vekna`](cli.md#vekna) has the full key table, the settings
and the line view that `--no-tui` gives.

```bash
vekna
```

The first `vekna` starts the daemon. `q` closes the window and the daemon keeps
running, so the casts carry on.

## Read the two pages

![The window on project shop: the casts that run or ask under their rituals
and the ended casts under finished on the left, the output of a running
ci_watch cast on the right](assets/tui-overview.svg)

The left page is the contents: project, ritual, the ritual's casts newest
first, and their rites. The right page is the line under the cursor in full,
with its output below. The output follows the newest line until you scroll up.
The branch of a project is read off git every few seconds, because a cast can
switch it.

`j` and `k` move the cursor down and up. `h` moves it to the line above in the
tree.

A cast is one line. The glyph says its state:

| Glyph | The cast |
| --- | --- |
| `▶` | runs |
| `⏸` | waits on your answer |
| `◷` | waits on a cast it queued |
| `↻` | recovers from a step that raised |
| `…` | is queued and not started yet |
| `✓` | finished |
| `✗` | failed |
| `⚠` | lost its connection; `vekna cast --continue` carries it on |

A running cast shows `…` and the rite it is on now. A cast shows `@now` while
it lives. Once it ended, it shows the slot it began in: `@<1h`, `@<3h`, `@<6h`,
`@<12h`, `@<1d`, then `@2d ago`.

A ritual line holds the casts that still run or ask. A cast that ended moves
under the `finished` line of its project, which lists every ended cast by
ritual. A cast that another cast queued hangs under that cast and says its
ritual. A cast line says no argument: the right page has them.

A cast that ended like the cast before it is not drawn. It has the same ritual
and arguments, it began in the same slot, and its status is the same, as are
the statuses of the casts it queued. The newest cast of the streak stands for
it and says how long it is: `x8`. A slot is one line unless a cast in it
failed.

The line of the project counts its casts by state: `shop (1 asks, 1 fail, 1
running)`. Asks and fails are the casts that need you. A running cast needs
nothing from you.

## Find the cast that waits on you

![The cursor on a pr_fix cast that asks; the top line names the cast and says
t answers it](assets/tui-asks.svg)

A cast that waits is the yellow line on top. When the cursor is on another
line, the top line says how many casts wait. `w` moves the cursor to the next
one.

The top line then names the cast and says who holds its question:

- `open`: nobody answers it yet.
- `asked at its terminal`: the terminal that typed `vekna cast` asks it.
- `taken over here`: this window holds it.
- `claimed elsewhere`: another window holds it.

## Take a cast over and answer it

![A pr_fix cast taken over: its rite tree on the left, its output ending in
the question "Push fix-discount-rounding?" and the answer line with "yes" typed
in](assets/tui-takeover.svg)

`t` takes over the cast under the cursor.

1. The left page opens the whole rite tree of the cast.
2. The right page shows its output. The question is at the end, with the
   answers it takes on the line below.
3. Type the answer on the line under the output and press Enter.

The window claims every question the cast asks while you hold it. An answer the
question does not offer is refused before it leaves the window. The contents
take no keys during a takeover. A question from another cast shows as one line
under the contents.

The takeover ends in three ways:

- You press Esc. The open questions go back to whoever answered them before.
- The cast ends.
- The cast asks nothing for five seconds after an answer.

A takeover covers that one cast. A cast it queued is taken over on its own.

To answer without a takeover, put the cursor on the cast and type
`a <answer>`.

## Open a cast and read why it failed

![A failed ci_watch cast opened to its rites; the cursor is on the failed
gave_up rite and the right page shows its whole error](assets/tui-rites.svg)

`space` on a cast opens its whole rite tree. `space` again closes it.

A rite line shows how long the rite took. A failed rite shows the first words
of its error. Put the cursor on the rite: the right page shows the whole error
and the output of that rite alone.

`s` on a failed cast marks it seen, and `s` again takes the mark back. A seen
cast keeps its `✗` and loses the red, and no fold or project line counts it as
a fail. The daemon keeps the mark, so every window shows it, and a window you
close and open again shows it too.

## Fold what you do not watch

![Two rituals and the finished line folded to one line each; the ci_watch
line says 1 running, the finished line says 1 fail, and the right page lists
the running ci_watch cast](assets/tui-fold.svg)

`space` on a project, a ritual or the `finished` line folds it. The folded
line says what still happens under it: `▸ ci_watch (1 fail, 1 running)`. A
project line always says it. `w` and `t` still reach a cast that asks under a
fold.

`f` folds every project, ritual and `finished` line at once. When they are all
folded, `f` opens them all again.

The window folds the tree once to fit its height, so that the tree needs no
scrolling. It does this when it opens, once the daemon has replayed its casts,
and each time `g` or `p` changes what it shows. It keeps as much as fits, in
this order:

1. Every running cast open to its whole rite tree.
2. `finished` folded.
3. The running casts back to one line.
4. Every project where nothing runs folded.
5. Every project folded.

After that the folds are yours. A line wider than the page is cut. The tree
does not scroll sideways.

The right page of a ritual lists its casts with their state, their time and
their flags.

## Look at older casts

![The history view: ended casts grouped under two days, each with the time it
ended and its ritual](assets/tui-history.svg)

A cast stays in the tree for a day after it ends. After that it moves to the
history view. `H` opens the history view and `H` again goes back to the tree.
The hint line says how many casts the history view holds: `H history (4)`.
While no cast is old enough, `H` stays in the tree view and says so.

The history view groups casts by the day they ended, newest first. Both views
hold what the daemon has seen since it started. `vekna log` has the rest.

[`history_after`](cli.md#vekna) sets how long an ended cast stays in the tree.

## Start and cancel a cast

![The command line at the bottom of the window with "c pr_fix --pr 415" typed
in](assets/tui-command.svg)

`c` opens the command line with `c` typed in. Add the ritual and its flags,
the same flags `vekna cast` takes, and press Enter:

```text
c pr_fix --pr 415
```

The cast runs in the directory you opened the window in. It has no terminal,
so it asks its questions here. A ritual that does not exist, or a flag that
does not validate, shows as that cast failing, with the reason on its right
page.

`x` cancels the running cast under the cursor. The first `x` says which cast
it will cancel. The second `x` cancels it.

`:` opens the command line empty. Esc closes it.

## See every project

![Two projects, blog and shop, in one tree; the cursor is on a write_tests
cast of blog](assets/tui-every.svg)

`g` shows the casts of every project. `p` goes back to the project you opened
the window in. A project is a repository: every worktree of one repository
groups under the same project line. A directory in no repository is its own
project.

Enter on a project line shows that project alone. The window is then on that
project: the bottom line names it, and it lists only the casts of that project.
`g` shows every project again, and `◆` marks the project the window is on.

A cast you start with `c` runs in the project the window is on, whatever the
scope shows. In the project you opened the window in, that is the directory you
opened it in. In another project it is the main checkout of that repository,
and never one of its worktrees. A new window starts on the project you open it
in.
