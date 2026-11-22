import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Log, Static, Tree
from textual.widgets.tree import TreeNode
from typing_extensions import override

from vekna.pacts.casts import Casts, CastView
from vekna.wire import (
    CastCancelRequested,
    DecideClaimed,
    DecideReleased,
    DecideRequested,
    WireMessage,
    allowed_answers,
)

from .cast_text import counted, labelled, live, named
from .commands import request_cast, send_answer
from .contents import Counts, Entry, Reading, cast_key, contents, historic, walked
from .page import head, holder, line_text, output, taken_head
from .screen import ordered, scoped

_COALESCE_SECONDS = 0.1
_TICK_SECONDS = 1.0
_BRANCH_SECONDS = 3.0
_NOTHING_WAITING = "nothing to answer — pick a waiting cast first"
_ASKS_NOTHING = "the cast asks nothing right now"
_NOTHING_TO_TAKE = "only a running cast can be taken over"
_ANSWER_HERE = "answer here"


# `old` is how many ended casts the history view holds.
def _hint(old: int = 0) -> str:
    return (
        f"space open/fold · H history{f' ({old})' if old else ''} · w next asking"
        " · t take over · x cancel · : command · g/p scope · q quit"
    )


# The contents tree. Its folds are the window's own, not the widget's: space
# folds the line under the cursor through the app, and a folded line is drawn
# as a leaf carrying what still happens under it.
class Contents(Tree[str]):
    ICON_NODE = "▸ "
    ICON_NODE_EXPANDED = "▾ "
    DEFAULT_CSS = """
    Contents > .tree--guides,
    Contents > .tree--guides-hover,
    Contents > .tree--guides-selected { color: $panel; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("space", "app.fold", "fold", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("h", "cursor_parent", show=False),
    ]


# What a window is opened with: its project, the directory a ritual started
# from it runs in, how long after it ended a cast moves to the history view,
# and the title it shows: the versions of this vekna and of its daemon.
@dataclass(frozen=True)
class Opened:
    project: str
    root: str
    history_after: timedelta
    title: str = "vekna"


# Where the window opened — its project, the directory a ritual started from it
# runs in, and the title it opened with — and whether it shows every project
# instead.
@dataclass
class _Scope:
    home: str
    root: str
    title: str
    every: bool = False


# The claims this window made, the cast it has taken over, and the prompts of
# that cast it claimed. Each is claimed once: a claim another window takes
# after that stays theirs.
@dataclass
class _Claims:
    mine: set[str] = field(default_factory=set)
    taken: str | None = None
    asked: set[str] = field(default_factory=set)


# The contents last drawn: the line under the cursor, their shape — each line's
# key, the key it hangs under, and whether it opens — a node per line, and each
# line's entry.
@dataclass
class _Drawn:
    cursor: str | None = None
    shape: tuple[tuple[str, str | None, bool], ...] = ()
    nodes: dict[str, TreeNode[str]] = field(default_factory=dict)
    entries: dict[str, Entry] = field(default_factory=dict)


# Where the cursor goes when its line goes: up the lines it hung under, to the
# nearest one still drawn.
def _kept(
    *, key: str | None, parents: dict[str, str | None], nodes: dict[str, TreeNode[str]]
) -> str | None:
    if key is None or key in nodes:
        return key
    return _kept(key=parents.get(key), parents=parents, nodes=nodes)


# Whether the output follows its newest line, the line it was left on when it
# last did, and the line under the cursor it was drawn for. Scrolling up off
# that line stops the follow; reaching the end starts it again.
@dataclass
class _Follow:
    on: bool = True
    at: float = 0
    page: str | None = None


# What the window is showing and what it has done: the folds of the contents,
# whether it needs repainting, the cast one more x cancels, the branch each tree
# was last seen on, its claims, the contents drawn, and the output's follow.
@dataclass
class _View:
    reading: Reading
    dirty: bool = True
    arming: str | None = None
    branches: dict[str, str | None] = field(default_factory=dict)
    claims: _Claims = field(default_factory=_Claims)
    drawn: _Drawn = field(default_factory=_Drawn)
    follow: _Follow = field(default_factory=_Follow)


# Where a waiting question shows: loud on top for the cast in view, and during
# a takeover one line under the contents for the casts that ask elsewhere.
@dataclass
class _Asks:
    here: Static = field(default_factory=lambda: Static(id="ask", markup=False))
    elsewhere: Static = field(
        default_factory=lambda: Static(id="elsewhere", markup=False)
    )


@dataclass
class _Widgets:
    ask: _Asks = field(default_factory=_Asks)
    contents: Contents = field(default_factory=lambda: Contents("all", id="contents"))
    head: Static = field(default_factory=lambda: Static(id="head", markup=False))
    log: Log = field(default_factory=lambda: Log(id="log"))
    note: Static = field(default_factory=lambda: Static(id="note", markup=False))
    command: Input = field(
        default_factory=lambda: Input(id="command", select_on_focus=False)
    )
    hint: Static = field(default_factory=lambda: Static(_hint(0), id="hint"))


# A book of the daemon's casts. The left page is the contents: project, ritual,
# its casts newest first, their rites — every cast as one line, a running one
# with `…` and the rite it is on, until space opens its whole rite tree. `H`
# turns it to the history view, the casts that ended long ago, by day. The
# right page is the line under the cursor in full, and the output it is making.
# A question waiting anywhere is the loud line on top. The command line shows
# only while it is being typed into. `t` takes a cast over: the right page
# stays on it, every prompt it asks is claimed and answered on the command
# line, and the contents take no keys until Esc hands the prompts back.
class VeknaApp(App[None]):
    TITLE = "vekna"
    CSS = """
    #ask {
        display: none; height: auto; padding: 0 1;
        background: $warning 25%; text-style: bold;
    }
    #body { height: 1fr; }
    #left { width: 46; max-width: 50%; border-right: vkey $panel; }
    #contents { height: 1fr; padding: 0 1; }
    #elsewhere { display: none; height: auto; padding: 0 1; color: $warning; }
    #page { width: 1fr; padding: 0 1; }
    #head { height: auto; max-height: 50%; }
    #log { height: 1fr; margin-top: 1; }
    #note { height: auto; padding: 0 1; color: $warning; }
    #command { display: none; border: none; height: 1; }
    #foot { height: 1; }
    #hint { width: 1fr; padding: 0 1; color: $text-muted; }
    #version { width: auto; padding: 0 1; color: $text-muted; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "quit"),
        Binding("colon", "command('')", "command"),
        Binding("c", "command('c ')", "cast"),
        Binding("t", "take", "answer"),
        Binding("w", "next_waiting", "next waiting"),
        Binding("x", "cancel", "cancel"),
        Binding("H", "history", "history"),
        Binding("g", "every", "every project"),
        Binding("p", "home", "this project"),
        Binding("a", "command('a ')", "type an answer", show=False),
        Binding("escape", "close_command", show=False),
    ]

    def __init__(
        self,
        *,
        casts: Casts,
        opened: Opened,
        send: Callable[[WireMessage], None],
        branch_of: Callable[[str], Awaitable[str | None]],
    ) -> None:
        super().__init__()
        self._casts = casts
        self._scope = _Scope(home=opened.project, root=opened.root, title=opened.title)
        self._send = send
        self._branch_of = branch_of
        self._view = _View(reading=Reading(history_after=opened.history_after))
        self._w = _Widgets()

    @override
    def compose(self) -> ComposeResult:
        yield self._w.ask.here
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield self._w.contents
                yield self._w.ask.elsewhere
            with Vertical(id="page"):
                yield self._w.head
                yield self._w.log
        yield self._w.note
        yield self._w.command
        with Horizontal(id="foot"):
            yield self._w.hint
            yield Static(self._scope.title, id="version", markup=False)

    def on_mount(self) -> None:
        tree = self._w.contents
        tree.show_root = False
        tree.auto_expand = False
        tree.focus()
        self.set_interval(_COALESCE_SECONDS, self._repaint)
        self.set_interval(_TICK_SECONDS, self.changed)
        self.set_interval(_BRANCH_SECONDS, self._look_up_branches)
        self.call_later(self._look_up_branches)

    def changed(self) -> None:
        self._view.dirty = True

    def say(self, note: str) -> None:
        self._w.note.update(note)

    # --- what the operator does ---

    # A taken-over cast has the line for its answers, so a command's prefix
    # stays out of it.
    def action_command(self, prefix: str) -> None:
        line = self._w.command
        line.display = True
        line.value = "" if self._view.claims.taken else prefix
        line.cursor_position = len(prefix)
        line.focus()

    def action_close_command(self) -> None:
        claims = self._view.claims
        if (view := self._taken()) is not None:
            # Heard back from the daemon or not, every claim still open goes.
            for request_id in claims.asked.intersection(view.waiting):
                self._send(
                    DecideReleased(cast_id=view.hello.cast_id, request_id=request_id)
                )
            self._leave(f"left {labelled(view.hello)} — its prompts are handed back")
            return
        line = self._w.command
        line.value = ""
        line.display = False
        self._w.contents.focus()

    def action_every(self) -> None:
        self._scope.every = True
        self.changed()

    def action_home(self) -> None:
        self._scope.every = False
        self.changed()

    def action_history(self) -> None:
        reading = self._view.reading
        reading.history = not reading.history
        self.say("history view" if reading.history else "tree view")
        self.changed()

    # On a cast, its whole rite tree, or back to the one line it was. On any
    # other line a fold hides what is under it, and a folded line opens again.
    # `…` and a line with nothing under it have nothing to fold.
    def action_fold(self) -> None:
        if (entry := self._entry()) is None or not entry.children:
            return
        # Symmetric difference: a line in the set goes out, one out goes in.
        self._view.reading.toggled ^= {entry.key}
        self.changed()

    # The cursor onto the next line down that is waiting on the operator — a
    # cast that asks, or a fold one hides in — wrapping round to the top. The
    # history view never holds a cast that asks, so `w` leaves it for the tree.
    def action_next_waiting(self) -> None:
        reading = self._view.reading
        if not reading.history:
            self._move_to_waiting()
            return
        reading.history = False
        self.say("tree view")
        self.changed()
        self._repaint()
        self._w.contents.call_after_refresh(self._move_to_waiting)

    def _move_to_waiting(self) -> None:
        keys = list(self._view.drawn.nodes)
        cursor = self._view.drawn.cursor
        start = keys.index(cursor) + 1 if cursor in keys else 0
        for index in list(range(start, len(keys))) + list(range(start)):
            entry = self._view.drawn.entries[keys[index]]
            asking = entry.kind == "cast" and entry.counts.asks
            if asking or (entry.folded and entry.counts.asks):
                self._move_to(keys[index])
                return
        self.say("no cast is waiting on you")

    # Twice, on the same cast: the first x says what the second one does.
    def action_cancel(self) -> None:
        view = self._focused()
        if view is None or view.status != "running":
            self._view.arming = None
            self.say("only a running cast can be cancelled")
            return
        named_cast = labelled(view.hello)
        if self._view.arming != view.hello.cast_id:
            self._view.arming = view.hello.cast_id
            self.say(f"x again cancels {named_cast}")
            return
        self._view.arming = None
        self._send(CastCancelRequested(cast_id=view.hello.cast_id))
        self.say(f"asked {named_cast} to stop")

    # The cast under the cursor, or the first one that asks under a fold. The
    # line its answers are typed on opens at once, and stays open.
    def action_take(self) -> None:
        claims = self._view.claims
        if claims.taken is not None:
            return
        found = self._waiting()
        view = found[0] if found is not None else self._focused()
        if view is None or not live(view):
            self.say(_NOTHING_TO_TAKE)
            return
        claims.taken = view.hello.cast_id
        self._w.contents.disabled = True
        self._w.command.placeholder = _ANSWER_HERE
        self.action_command("")
        self.say(f"took over {labelled(view.hello)}")
        self.changed()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        typed = event.value.strip()
        if self._view.claims.taken is not None:
            self._w.command.value = ""
            self._answer(typed)
            return
        self.action_close_command()
        if typed.lower() in {"q", "quit"}:
            self.exit()
        elif typed.lower() in {"g", "p"}:
            self._scope.every = typed.lower() == "g"
        elif typed.lower() == "t":
            self.action_take()
        elif typed.lower().startswith("c "):
            self.say(
                request_cast(typed=typed[2:], root=self._scope.root, send=self._send)
            )
        elif typed.lower().startswith("a "):
            self._answer(typed[2:].strip())
        elif typed:
            self.say(f"{typed!r} means nothing here — {_hint()}")
        self.changed()

    # A cleared tree highlights its hidden root, which is no line to stand on.
    # A terminal that reports the mouse keeps its own selection off, so what
    # the operator dragged over is copied the moment they let go.
    def on_text_selected(self) -> None:
        if text := self.screen.get_selected_text():
            self.copy_to_clipboard(text)
            self.say(f"copied {len(text)} characters")

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
        if (key := event.node.data) is None:
            return
        if key != self._view.drawn.cursor:
            self._view.drawn.cursor = key
            self._view.arming = None
        self.changed()

    def _answer(self, typed: str) -> None:
        if (found := self._waiting()) is None:
            self.say(_ASKS_NOTHING if self._view.claims.taken else _NOTHING_WAITING)
            return
        _, request = found
        if (
            refused := send_answer(request=request, typed=typed, send=self._send)
        ) is not None:
            self.say(refused)

    def _taken(self) -> CastView | None:
        return self._casts.casts.get(self._view.claims.taken or "")

    # The line the window acts on and the right page shows: the one under the
    # cursor, or the cast taken over, wherever the cursor was left.
    def _entry(self) -> Entry | None:
        if (view := self._taken()) is not None:
            return Entry(
                key=cast_key(view.hello.cast_id),
                kind="cast",
                name=view.hello.ritual,
                counts=Counts(),
                view=view,
            )
        return self._view.drawn.entries.get(self._view.drawn.cursor or "")

    # The cast the line under the cursor belongs to: none for a project or a
    # ritual, which hold many.
    def _focused(self) -> CastView | None:
        entry = self._entry()
        if entry is None or entry.view is None:
            return None
        return self._casts.casts.get(entry.view.hello.cast_id)

    # The first cast under the cursor that asks, a folded one included: a fold
    # says it asks, so it answers too.
    def _waiting(self) -> tuple[CastView, DecideRequested] | None:
        if (entry := self._entry()) is None:
            return None
        for cast_id in entry.casts:
            view = self._casts.casts.get(cast_id)
            if view is not None and view.waiting:
                return view, next(iter(view.waiting.values())).request
        return None

    def _claim(self, request: DecideRequested) -> None:
        claim_id = uuid4().hex
        self._view.claims.mine.add(claim_id)
        self._send(
            DecideClaimed(
                cast_id=request.cast_id,
                request_id=request.request_id,
                claim_id=claim_id,
            )
        )

    # Every prompt the taken cast asks is claimed as it comes. A cast that
    # ended has nothing left to hand back.
    def _hold(self) -> None:
        claims = self._view.claims
        if claims.taken is None:
            return
        view = self._taken()
        if view is None or not live(view):
            self._leave("the cast taken over has ended")
            return
        for request_id, prompt in view.waiting.items():
            if request_id not in claims.asked:
                claims.asked.add(request_id)
                self._claim(prompt.request)

    def _leave(self, said: str) -> None:
        claims = self._view.claims
        claims.taken = None
        claims.asked.clear()
        line = self._w.command
        line.placeholder = ""
        line.value = ""
        line.display = False
        self._w.contents.disabled = False
        self._w.contents.focus()
        self.say(said)
        self.changed()

    def _move_to(self, key: str) -> None:
        self._view.drawn.cursor = key
        self._w.contents.move_cursor(self._view.drawn.nodes[key])
        self.changed()

    # --- painting ---

    def _listed(self) -> list[CastView]:
        project = None if self._scope.every else self._scope.home
        return ordered(scoped(list(self._casts.casts.values()), project))

    async def _look_up_branches(self) -> None:
        roots = {
            view.hello.project_root
            for view in self._listed()
            if live(view) or view.hello.project_root not in self._view.branches
        }
        found = await asyncio.gather(*(self._branch_of(root) for root in roots))
        self._view.branches.update(zip(roots, found, strict=True))
        self.changed()

    def _repaint(self) -> None:
        # A tick can land while the app is closing and its widgets are gone.
        mounted = self._w.contents.is_mounted
        # A layout that lands after the last scroll to the end, or a resized
        # window, leaves the output short of its newest line.
        if mounted and not self._view.dirty and self._follows():
            self._to_end(self._w.log.scroll_y)
        if not self._view.dirty or not mounted:
            return
        self._view.dirty = False
        self._hold()
        taken = self._taken()
        listed = self._listed()
        now = datetime.now(UTC)
        where = "all projects" if self._scope.every else named(self._scope.home)
        self.sub_title = f"{counted(listed) or 'no casts'}  ({where})"
        reading = self._view.reading
        old = sum(historic(view, reading, now) for view in listed)
        self._w.hint.update(
            _hint(old)
            if taken is None
            else f"taken over {labelled(taken.hello)} · enter answers"
            " · esc leaves and hands the prompts back"
        )
        self._paint_contents(listed, now)
        entry = self._entry()
        self._paint_ask(listed, self._focused())
        branches = self._view.branches
        self._w.head.update(
            head(entry, branches=branches, now=now)
            if taken is None
            else taken_head(taken, branches=branches, now=now)
        )
        self._paint_output(entry)

    # Rebuilt only when a line comes or goes, relabelled otherwise, so the
    # cursor stays on the line the operator put it on. When its line goes, the
    # cursor goes to the nearest line above it that is still there; with none,
    # to the first cast, which is what a window opens to look at.
    def _paint_contents(self, listed: list[CastView], now: datetime) -> None:
        drawn, reading = self._view.drawn, self._view.reading
        history = reading.history
        lines = walked(contents(listed, reading, now))
        entries = {entry.key: entry for entry, _ in lines}
        shape = tuple((entry.key, parent, bool(entry.shown)) for entry, parent in lines)
        if shape == drawn.shape:
            drawn.entries = entries
            for key, node in drawn.nodes.items():
                node.set_label(line_text(entries[key], now, history=history))
            return
        tree = self._w.contents
        tree.clear()
        nodes: dict[str, TreeNode[str]] = {}
        for entry, parent in lines:
            under = nodes[parent] if parent is not None else tree.root
            text = line_text(entry, now, history=history)
            nodes[entry.key] = (
                under.add(text, data=entry.key, expand=True)
                if entry.shown
                else under.add_leaf(text, data=entry.key)
            )
        parents = {key: parent for key, parent, _ in drawn.shape}
        cursor = _kept(key=drawn.cursor, parents=parents, nodes=nodes)
        if cursor is None and lines:
            casts = [entry.key for entry, _ in lines if entry.kind == "cast"]
            cursor = casts[0] if casts else lines[0][0].key
        self._view.drawn = _Drawn(
            cursor=cursor, shape=shape, nodes=nodes, entries=entries
        )
        # A node has no line until the tree has laid it out, and the cursor
        # the rebuild left on the first line says so on its way.
        if cursor is not None:
            tree.call_after_refresh(tree.move_cursor, nodes[cursor])

    # Loud while the cast in view waits on the operator, and a pointer to the
    # next one while some other cast does: a question nobody sees is a cast
    # that never ends. During a takeover the top line is the taken cast's
    # alone, and what asks elsewhere is one line under the contents.
    def _paint_ask(self, listed: list[CastView], view: CastView | None) -> None:
        taken = self._view.claims.taken is not None
        others = [other for other in listed if other.waiting and other is not view]
        text = ""
        if view is not None and view.waiting:
            prompt = next(iter(view.waiting.values()))
            request = prompt.request
            allowed = allowed_answers(options=request.options, free=request.free)
            takes = " | ".join(allowed) if allowed is not None else "any answer"
            holds = holder(view, prompt, self._view.claims.mine)
            key = "enter" if taken else "t"
            text = f"⏸ {request.prompt}\n  {takes} · {holds} · {key} answers it"
        elif others and not taken:
            many = "1 cast waits" if len(others) == 1 else f"{len(others)} casts wait"
            text = f"⏸ {many} on you · w goes to it"
        ask = self._w.ask
        ask.here.display = bool(text)
        ask.here.update(text)
        too = ""
        if taken and len(others) == 1:
            too = f"? {labelled(others[0].hello)} asks too"
        elif taken and others:
            too = f"? {len(others)} other casts ask too"
        ask.elsewhere.display = bool(too)
        ask.elsewhere.update(too)

    # Rewritten only when it changed. It follows the newest line unless the
    # operator scrolled up off where it last left it, and keeps following when
    # the page above it grows and pushes the end further down.
    def _paint_output(self, entry: Entry | None) -> None:
        log, follow = self._w.log, self._view.follow
        if (page := None if entry is None else entry.key) != follow.page:
            follow.page, follow.on = page, True
        else:
            self._follows()
        lines = output(entry)
        if list(log.lines) != lines:
            log.auto_scroll = False
            log.clear()
            log.write_lines(lines)
        if follow.on:
            log.call_after_refresh(self._to_end, log.scroll_y)

    def _follows(self) -> bool:
        log, follow = self._w.log, self._view.follow
        # An upward scroll that has only begun still rounds to the end.
        leaving = log.scroll_target_y < log.scroll_y
        if log.is_vertical_scroll_end and not leaving:
            follow.on = True
        elif leaving or log.scroll_y < follow.at:
            follow.on = False
        return follow.on

    # A scroll the operator made while the refresh was pending stands, one that
    # has only begun included; Textual clamping it onto a shorter page's end is
    # no scroll of theirs.
    def _to_end(self, asked_at: float) -> None:
        log = self._w.log
        if log.scroll_target_y < log.scroll_y:
            return
        if log.scroll_y != asked_at and not log.is_vertical_scroll_end:
            return
        log.scroll_end(animate=False, immediate=True, x_axis=False)
        self._view.follow.at = log.max_scroll_y
