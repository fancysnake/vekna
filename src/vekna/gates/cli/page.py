from datetime import datetime
from pathlib import Path

from rich.text import Text

from vekna.pacts.casts import CastView, Prompt, RiteStatus, RiteView
from vekna.wire import SHORT_ID, CastHello

from .cast_text import ago, carried, clipped, clock, counted, elapsed, live, word
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
    "error": Text("✗", "red"),
    "cancelled": Text("⊘", "dim"),
}
_ASKS = "bold yellow"
_FAILS = "bold red"
_RUNNING = "green"
NO_CAST = "no cast here — c starts one"


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


def line_text(entry: Entry, now: datetime) -> Text:
    view, rite = entry.view, entry.rite
    if rite is not None and view is not None:
        text = _rite_label(view, rite, now)
    elif entry.kind == "more":
        text = Text("…", "dim")
    elif view is not None:
        text = _cast_label(view, now)
    else:
        text = Text(entry.name, "bold" if entry.kind == "project" else "")
    if entry.folded or entry.kind == "project":
        text.append_text(tally(entry.counts))
    # A folded line is drawn as a leaf, which the tree gives no arrow.
    if entry.folded:
        text = Text("▸ ") + text
    return text


def _cast_label(view: CastView, now: datetime) -> Text:
    text = Text.assemble(
        _CAST_LOOK[word(view)].copy(),
        " ",
        (ago(view, now), _ASKS if view.waiting else ""),
        (f"  {view.hello.cast_id[:SHORT_ID]}", "dim"),
    )
    if view.waiting:
        text.append("  asks", _ASKS)
    return text


def _took(rite: RiteView, now: datetime) -> str:
    until = rite.finished_at or now
    return clock((until - rite.started.started_at).total_seconds())


def _rite_label(view: CastView, rite: RiteView, now: datetime) -> Text:
    medium = "italic" if rite.started.category == "medium" else ""
    text = Text.assemble(
        _RITE_LOOK[rite.status].copy(),
        " ",
        (rite.started.name, medium),
        (f"  {_took(rite, now)}", "dim"),
    )
    if rite.error is not None:
        text.append(f"  {clipped(rite.error, _ERROR)}", "red")
    if any(
        prompt.request.rite_id == rite.started.rite_id
        for prompt in view.waiting.values()
    ):
        text.append("  asks", _ASKS)
    return text


def _flags(hello: CastHello) -> str:
    return " ".join(f"--{name} {value}" for name, value in hello.components.items())


# The right page's top: what the line under the cursor is, in full.
def head(
    entry: Entry | None, *, branches: dict[str, str | None], now: datetime
) -> Text:
    if entry is None:
        return Text(NO_CAST)
    view, rite = entry.view, entry.rite
    if rite is not None:
        return _rite_head(rite, now)
    if view is not None:
        return _cast_head(view, branches, now)
    if entry.kind == "ritual":
        return _ritual_head(entry, now)
    return _project_head(entry, branches)


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
        text.append(
            f"\ntree {view.blocked.path} left blocked: {view.blocked.reason}", "red"
        )
    depth: dict[str, int] = {}
    for entry, parent in walked(rite_tree(view)):
        depth[entry.key] = depth.get(parent or "", -1) + 1
        text.append("\n" + "  " * depth[entry.key])
        text.append_text(line_text(entry, now))
    return text


def _rite_head(rite: RiteView, now: datetime) -> Text:
    text = Text.assemble(
        (rite.started.name, "bold"), f"  {rite.status}  {_took(rite, now)}"
    )
    if rite.error is not None:
        text.append(f"\n{rite.error}", "red")
    return text


# The right page's output: the rite under the cursor, or for a cast the latest
# rite still talking, else the last one that said anything. Why a cast ended
# follows it.
def output(entry: Entry | None) -> list[str]:
    if entry is None or entry.view is None:
        return []
    view = entry.view
    rite = entry.rite or _shown_rite(view)
    lines = [] if rite is None else list(rite.deltas)
    if entry.rite is None and view.detail and not live(view):
        lines += ["", *view.detail.splitlines()]
    # Log.write_lines drops an empty line, so a blank one is drawn as a space.
    return [line or " " for line in lines]


def _shown_rite(view: CastView) -> RiteView | None:
    rites = list(view.rites.values())
    talking = [rite for rite in rites if rite.status == "running" and rite.deltas]
    said = talking or [rite for rite in rites if rite.deltas]
    return said[-1] if said else None
