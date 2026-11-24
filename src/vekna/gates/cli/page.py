from datetime import datetime
from pathlib import Path
from typing import assert_never

from rich.text import Text

from vekna.pacts.casts import CastView, Prompt, RiteStatus, RiteView
from vekna.wire import SHORT_ID, CastHello, allowed_answers

from .cast_text import (
    ago,
    carried,
    clipped,
    clock,
    counted,
    elapsed,
    ended,
    labelled,
    live,
    printable,
    top_prompt,
    word,
)
from .contents import Counts, Entry, rite_tree, walked

# A tree row holds the first line of an error, cut to this: the whole of it is
# on the right page, where it wraps.
_ERROR = 32
# The glyph and its colour carry the status; a waiting cast is the loudest
# thing on screen because it is the one that cannot go on without the operator.
_CAST_LOOK = {
    "queued": Text("…", "dim"),
    "running": Text("▶", "cyan"),
    "waiting": Text("⏸", "bold yellow"),
    "on child": Text("◷", "blue"),
    "recovering": Text("↻", "yellow"),
    "done": Text("✓", "green"),
    "failed": Text("✗", "red"),
    "aborted": Text("⚠", "red"),
}
_RITE_LOOK: dict[RiteStatus, Text] = {
    "running": Text("▶", "cyan"),
    "ok": Text("✓", "green"),
    "reported": Text("✗", "red"),
    "error": Text("✗", "red"),
    "cancelled": Text("⊘", "dim"),
}
_ASKS = "bold yellow"
_FAILS = "bold red"
_RUNNING = "green"
NO_CAST = "no cast here — c starts one"
LEAVES = "esc leaves"


def where(root: str) -> str:
    path, home = Path(root), Path.home()
    return str(Path("~", path.relative_to(home))) if path.is_relative_to(home) else root


# Who answers a prompt, as this window sees it: a claim id it minted is its own.
def holder(view: CastView, prompt: Prompt, mine: set[str]) -> str:
    if prompt.claim_id is None:
        return "asked at its terminal" if not view.hello.wired else "open"
    return "taken over here" if prompt.claim_id in mine else "claimed elsewhere"


# What still happens under a fold, loudest first. Asks and fails are what the
# operator acts on, so they are bold; running only says something is going on.
def tally(counts: Counts) -> Text:
    parts = [
        (counts.asks, "asks", _ASKS),
        (counts.fails, "fail", _FAILS),
        (counts.running, "running", _RUNNING),
    ]
    if not (shown := [(f"{n} {said}", style) for n, said, style in parts if n]):
        return Text()
    text = Text(" (", "dim")
    for index, (said, style) in enumerate(shown):
        if index:
            text.append(", ", "dim")
        text.append(said, style)
    text.append(")", "dim")
    return text


# A cast line says how long ago it began, in the history view when it ended.
def line_text(entry: Entry, now: datetime, *, history: bool = False) -> Text:
    view, rite = entry.view, entry.rite
    if rite is not None and view is not None:
        text = _rite_label(view, rite, now)
    elif entry.kind == "more":
        text = Text("…", "dim")
    elif view is not None:
        text = _cast_label(view, _cast_said(entry, view, now, history=history))
        if len(entry.streak) > 1:
            text.append(f"  x{len(entry.streak)}", "dim")
    else:
        text = Text(entry.name, "bold" if entry.kind in {"project", "day"} else "")
        if entry.kind == "finished":
            text.stylize("dim")
    # A cast's own glyph already says what its fold would.
    if (entry.folded and entry.kind != "cast") or entry.kind == "project":
        text.append_text(tally(entry.counts))
    # The tree gives an arrow only to a line with lines under it, which a
    # folded cast keeps for the casts it queued, so the fold says so itself.
    if entry.folded:
        text = Text("▸ ") + text
    return text


# A cast under the cast that queued it says its ritual, which no line above it
# does; any other says when it began.
def _cast_said(entry: Entry, view: CastView, now: datetime, *, history: bool) -> str:
    if history:
        return _ended_said(view)
    if entry.nested:
        return view.hello.ritual
    return ago(view, now)


def _ended_said(view: CastView) -> str:
    return f"{ended(view).astimezone():%H:%M}  {view.hello.ritual}"


def _cast_label(view: CastView, said: str) -> Text:
    text = Text.assemble(
        _CAST_LOOK[word(view)].copy(),
        " ",
        (said, _ASKS if view.waiting else ""),
        (f"  {view.hello.cast_id[:SHORT_ID]}", "dim"),
    )
    if view.waiting:
        text.append("  asks", _ASKS)
    return text


def _took(view: CastView, rite: RiteView, now: datetime) -> str:
    until = view.rite_finished_at(rite) or now
    return clock((until - rite.started.started_at).total_seconds())


def _rite_label(view: CastView, rite: RiteView, now: datetime) -> Text:
    medium = "italic" if rite.started.category == "medium" else ""
    text = Text.assemble(
        _RITE_LOOK[view.rite_status(rite)].copy(),
        " ",
        (rite.started.name, medium),
        (f"  {_took(view, rite, now)}", "dim"),
    )
    if rite.error is not None:
        text.append(f"  {clipped(printable(rite.error), _ERROR)}", "red")
    if any(
        prompt.request.rite_id == rite.started.rite_id
        for prompt in view.waiting.values()
    ):
        text.append("  asks", _ASKS)
    return text


def _flags(hello: CastHello) -> str:
    return " ".join(f"--{name} {value}" for name, value in hello.components.items())


# The right page's top for a cast taken over: which cast, how to leave it, and
# the rite whose output is under it. The cast's rites are on the left page.
def taken_head(view: CastView) -> Text:
    rite = _shown_rite(view)
    return Text.assemble(
        (f" ◆ taken over · {labelled(view.hello)} ", "bold reverse"),
        (f" {LEAVES}\n", "dim"),
        ("no output yet" if rite is None else f"{rite.started.name} · live", "dim"),
    )


# The right page's top: what the line under the cursor is, in full.
def head(
    entry: Entry | None, *, branches: dict[str, str | None], now: datetime
) -> Text:
    if entry is None:
        return Text(NO_CAST)
    view, rite = entry.view, entry.rite
    if rite is not None and view is not None:
        return _rite_head(view, rite, now)
    if view is not None:
        text = _cast_head(view, branches, now)
        if len(entry.streak) > 1:
            since = f"{ended(entry.streak[-1]).astimezone():%a %H:%M}"
            text.append(
                f"\nx{len(entry.streak)} — every cast since {since} ended like this"
            )
        return text
    return _group_head(entry, branches, now)


def _group_head(entry: Entry, branches: dict[str, str | None], now: datetime) -> Text:
    match entry.kind:
        case "ritual" | "finished":
            return _ritual_head(entry, now)
        case "day":
            return _day_head(entry, now)
        case "project":
            return _project_head(entry, branches)
        case "cast" | "more" | "rite":
            return Text(NO_CAST)
        case _:
            assert_never(entry.kind)


def _project_head(entry: Entry, branches: dict[str, str | None]) -> Text:
    root = entry.views[0].hello.project_root
    return Text.assemble(
        (entry.name, "bold"),
        (f"\n{branches.get(root) or '—'} · {where(root)}", "dim"),
        f"\n{counted(entry.views)}",
    )


def _ritual_head(entry: Entry, now: datetime) -> Text:
    text = Text(entry.name, "bold")
    for view in entry.views:
        text.append("\n")
        text.append_text(_CAST_LOOK[word(view)].copy())
        text.append(f" {ago(view, now):<9} {view.hello.cast_id[:SHORT_ID]}  ")
        text.append(f"{word(view):<10} {elapsed(view, now):>7}  ", "dim")
        text.append(_flags(view.hello))
    return text


def _day_head(entry: Entry, now: datetime) -> Text:
    text = Text(entry.name, "bold")
    for view in entry.views:
        text.append("\n")
        text.append_text(_CAST_LOOK[word(view)].copy())
        text.append(f" {_ended_said(view)}  {view.hello.cast_id[:SHORT_ID]}  ")
        text.append(f"{word(view):<10} {elapsed(view, now):>7}  ", "dim")
        text.append(_flags(view.hello))
    return text


def _cast_head(view: CastView, branches: dict[str, str | None], now: datetime) -> Text:
    hello = view.hello
    root = hello.project_root
    text = Text.assemble(
        (f"{hello.ritual}  {hello.cast_id[:SHORT_ID]}", "bold"),
        f"  {word(view)}  {elapsed(view, now)}{carried(hello)}",
        (f"\n{branches.get(root) or '—'} · {where(root)}", "dim"),
    )
    if flags := _flags(hello):
        text.append(f"\n{flags}", "dim")
    if view.blocked is not None:
        blocked, reason = view.blocked, printable(view.blocked.reason)
        text.append(f"\ntree {blocked.path} left blocked: {reason}", "red")
    depth: dict[str, int] = {}
    for entry, parent in walked(rite_tree(view)):
        depth[entry.key] = depth.get(parent or "", -1) + 1
        text.append("\n" + "  " * depth[entry.key])
        text.append_text(line_text(entry, now))
    return text


def _rite_head(view: CastView, rite: RiteView, now: datetime) -> Text:
    text = Text.assemble(
        (rite.started.name, "bold"),
        f"  {view.rite_status(rite)}  {_took(view, rite, now)}",
    )
    if rite.error is not None:
        text.append(f"\n{printable(rite.error)}", "red")
    return text


# The right page's output: the rite under the cursor, or for a cast the latest
# rite still talking, else the last one that said anything. Why a cast ended
# follows it.
def output(entry: Entry | None) -> list[str]:
    if entry is None or entry.view is None:
        return []
    return cast_output(entry.view, entry.rite)


# The same for a cast on its own: `picked` is the rite chosen under it, if any.
def cast_output(view: CastView, picked: RiteView | None = None) -> list[str]:
    rite = picked or _shown_rite(view)
    said = [] if rite is None else list(rite.deltas)
    if picked is None and view.detail and not live(view):
        said += ["", *view.detail.splitlines()]
    # Log.write_lines drops an empty line, so a blank one is drawn as a space.
    return [printable(line) or " " for line in said]


# The output of a cast taken over ends with the question the answer line
# answers: the oldest one open.
def taken_output(view: CastView, mine: set[str]) -> list[str]:
    lines = cast_output(view)
    if (prompt := top_prompt(view)) is None:
        return lines
    request = prompt.request
    asked = printable(request.prompt).splitlines() or [""]
    allowed = allowed_answers(options=request.options, free=request.free)
    takes = " | ".join(allowed) if allowed is not None else "any answer"
    if prompt.claim_id is not None and prompt.claim_id not in mine:
        takes += " · claimed elsewhere"
    return [
        *lines,
        f"? {asked[0]}",
        *(f"  {more}" for more in asked[1:]),
        f"    {takes}",
    ]


def _shown_rite(view: CastView) -> RiteView | None:
    rites = list(view.rites.values())
    talking = [
        rite for rite in rites if view.rite_status(rite) == "running" and rite.deltas
    ]
    said = talking or [rite for rite in rites if rite.deltas]
    return said[-1] if said else None
