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

![The window on project shop: three rituals with their casts on the left, the
output of a running ci_watch cast on the right](assets/tui-overview.svg)

The left page is the contents: project, ritual, the ritual's casts newest
first, and their rites. The right page is the line under the cursor in full,
with its output below. The output follows the newest line until you scroll up.

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

A running cast shows `…` and the rite it is on now. The line of the project
counts what needs you: `shop (1 asks, 1 fail, 1 running)`.

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

To answer without a takeover, put the cursor on the cast and type
`a <answer>`.

## Open a cast and read why it failed

![A failed ci_watch cast opened to its rites; the cursor is on the failed
gave_up rite and the right page shows its whole error](assets/tui-rites.svg)

`space` on a cast opens its whole rite tree. `space` again closes it.

A rite line shows how long the rite took. A failed rite shows the first words
of its error. Put the cursor on the rite: the right page shows the whole error
and the output of that rite alone.

## Fold what you do not watch

![Three rituals folded to one line each; the ci_watch line says 1 fail, 1
running, and the right page lists its two casts](assets/tui-fold.svg)

`space` on a project or a ritual folds it. The folded line says what still
happens under it: `▸ ci_watch (1 fail, 1 running)`. `w` and `t` still reach a
cast that asks under a fold.

The right page of a ritual lists its casts with their state, their time and
their flags.

## Look at older casts

![The history view: ended casts grouped under two days, each with the time it
ended and its ritual](assets/tui-history.svg)

A cast stays in the tree for a day after it ends. After that it moves to the
history view. `H` opens the history view and `H` again goes back to the tree.
The hint line says how many casts the history view holds: `H history (4)`.

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
groups under the same project line.

A cast you start with `c` still runs in the directory of this window, whatever
the scope shows.
