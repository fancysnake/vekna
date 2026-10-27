import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.command import CommandPalette
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Log, Static, Tree
from textual.widgets.tree import TreeNode
from typing_extensions import override

from vekna.pacts.casts import Casts, CastView
from vekna.wire import (
    CastCancelRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    WireMessage,
    allowed_answers,
)

from .cast_text import counted, labelled, named
from .commands import request_cast, send_answer
from .contents import Entry, contents, walked
from .page import head, holder, line_text, output
from .screen import ordered, scoped

_COALESCE_SECONDS = 0.1
_TICK_SECONDS = 1.0
_BRANCH_SECONDS = 3.0
_HINT = (
    "space fold · e every cast · w next asking · t take over · x cancel"
    " · : command · g/p scope · q quit"
)
_NOTHING_WAITING = "nothing to answer — pick a waiting cast first"


# One prompt, answered here: the answers it allows as buttons, and a line to
# type into when it takes anything. Esc lets the claim go, and whoever was
# answering it before asks again.
class AnswerScreen(ModalScreen[str | None]):
    BINDINGS: ClassVar[list[BindingType]] = [Binding("escape", "let_go", "let go")]
    DEFAULT_CSS = """
    AnswerScreen { align: center middle; }
    #dialog { width: 70%; height: auto; border: thick $accent; padding: 1 2; }
    #options { height: auto; }
    """

    def __init__(self, *, label: str, request: DecideRequested) -> None:
        super().__init__()
        self._label = label
        self._request = request
        allowed = allowed_answers(options=request.options, free=request.free)
        self._free = allowed is None
        # Each button's answer, so a press is looked up rather than parsed.
        self._choices = {
            Button(escape(choice), id=f"choice-{index}"): choice
            for index, choice in enumerate(allowed or request.options or [])
        }

    @property
    def request_id(self) -> str:
        return self._request.request_id

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"{self._label}\n\n{self._request.prompt}", markup=False)
            with Horizontal(id="options"):
                yield from self._choices
            if self._free:
                yield Input(placeholder="answer in your own words", id="free")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(self._choices[event.button])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def action_let_go(self) -> None:
        self.dismiss(None)


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


# Where the window opened — its project, and the directory a ritual started
# from it runs in — and whether it shows every project instead.
@dataclass
class _Scope:
    home: str
    root: str
    every: bool = False


# The claims this window made, and the dialog answering one of them.
@dataclass
class _Claims:
    mine: set[str] = field(default_factory=set)
    dialog: AnswerScreen | None = None


# What the operator asked the contents to show: every cast or the running ones
# only, the lines folded, the failed casts already opened, and the cast on the
# page now.
@dataclass
class _Shown:
    everything: bool = False
    folded: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)
    opened: str | None = None


# The contents last drawn: the line under the cursor, their shape, a node per
# line, each line's entry, and the line each hangs under — which is where the
# cursor goes when its own line goes.
@dataclass
class _Drawn:
    cursor: str | None = None
    shape: tuple[tuple[str, str | None, bool], ...] = ()
    nodes: dict[str, TreeNode[str]] = field(default_factory=dict)
    entries: dict[str, Entry] = field(default_factory=dict)
    parents: dict[str, str | None] = field(default_factory=dict)


# Whether the output follows its newest line, the line it was left on when it
# last did, and the line under the cursor it was drawn for. Scrolling up off
# that line stops the follow; reaching the end starts it again.
@dataclass
class _Follow:
    on: bool = True
    at: float = 0
    page: str | None = None


# What the window is showing and what it has done: what the contents show,
# whether it needs repainting, the cast one more x cancels, the branch each tree
# was last seen on, its claims, the contents drawn, and the output's follow.
@dataclass
class _View:
    shown: _Shown = field(default_factory=_Shown)
    dirty: bool = True
    arming: str | None = None
    branches: dict[str, str | None] = field(default_factory=dict)
    claims: _Claims = field(default_factory=_Claims)
    drawn: _Drawn = field(default_factory=_Drawn)
    follow: _Follow = field(default_factory=_Follow)


# Held rather than queried: `query_one` searches whichever screen is on top,
# which is the answer dialog while one is up.
@dataclass
class _Widgets:
    ask: Static = field(default_factory=lambda: Static(id="ask", markup=False))
    contents: Contents = field(default_factory=lambda: Contents("all", id="contents"))
    head: Static = field(default_factory=lambda: Static(id="head", markup=False))
    log: Log = field(default_factory=lambda: Log(id="log"))
    note: Static = field(default_factory=lambda: Static(id="note", markup=False))
    command: Input = field(
        default_factory=lambda: Input(id="command", select_on_focus=False)
    )
    hint: Static = field(default_factory=lambda: Static(_HINT, id="hint"))


# A book of the daemon's casts. The left page is the contents: project, ritual,
# its casts newest first, their rites — by default only the running casts, each
# as `…` and the rite it is on. The right page is the line under the cursor in
# full, and the output it is making. A question waiting anywhere is the loud
# line on top. The command line shows only while it is being typed into.
class VeknaApp(App[None]):
    TITLE = "vekna"
    CSS = """
    #ask {
        display: none; height: auto; padding: 0 1;
        background: $warning 25%; text-style: bold;
    }
    #body { height: 1fr; }
    #contents {
        width: 46; max-width: 50%; padding: 0 1;
        border-right: vkey $panel;
    }
    #page { width: 1fr; padding: 0 1; }
    #head { height: auto; max-height: 50%; }
    #log { height: 1fr; margin-top: 1; }
    #note { height: auto; padding: 0 1; color: $warning; }
    #command { display: none; border: none; height: 1; }
    #hint { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "quit"),
        Binding("colon", "command('')", "command"),
        Binding("c", "command('c ')", "cast"),
        Binding("t", "take", "answer"),
        Binding("w", "next_waiting", "next waiting"),
        Binding("x", "cancel", "cancel"),
        Binding("e", "everything", "everything"),
        Binding("g", "every", "every project"),
        Binding("p", "home", "this project"),
        Binding("a", "command('a ')", "type an answer", show=False),
        Binding("escape", "close_command", show=False),
    ]

    def __init__(
        self,
        *,
        casts: Casts,
        project: str,
        root: str,
        send: Callable[[WireMessage], None],
        branch_of: Callable[[str], Awaitable[str | None]],
    ) -> None:
        super().__init__()
        self._casts = casts
        self._scope = _Scope(home=project, root=root)
        self._send = send
        self._branch_of = branch_of
        self._view = _View()
        self._w = _Widgets()

    @override
    def compose(self) -> ComposeResult:
        yield self._w.ask
        with Horizontal(id="body"):
            yield self._w.contents
            with Vertical(id="page"):
                yield self._w.head
                yield self._w.log
        yield self._w.note
        yield self._w.command
        yield self._w.hint

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

    def action_command(self, prefix: str) -> None:
        line = self._w.command
        line.display = True
        line.value = prefix
        line.cursor_position = len(prefix)
        line.focus()

    def action_close_command(self) -> None:
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

    def action_everything(self) -> None:
        self._view.shown.everything = not self._view.shown.everything
        self.say("every cast" if self._view.shown.everything else "running casts only")
        self.changed()

    # A fold hides what is under the line; a folded line opens again. A line
    # with nothing under it has nothing to fold.
    def action_fold(self) -> None:
        if (entry := self._entry()) is None:
            return
        folded = self._view.shown.folded
        if entry.key in folded:
            folded.discard(entry.key)
        elif entry.children:
            folded.add(entry.key)
        self.changed()

    # The cursor onto the next line down that is waiting on the operator — a
    # cast that asks, or a fold one hides in — wrapping round to the top.
    def action_next_waiting(self) -> None:
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

    # The oldest open prompt under the cursor, claimed so whoever else was
    # answering it stops, then asked in a dialog.
    def action_take(self) -> None:
        if (found := self._waiting()) is None:
            self.say(_NOTHING_WAITING)
            return
        view, request = found
        self._claim(request)
        dialog = AnswerScreen(label=labelled(view.hello), request=request)
        self._view.claims.dialog = dialog

        # A dialog closed because its prompt went has nothing to send.
        def answered(answer: str | None) -> None:
            if self._view.claims.dialog is not dialog:
                return
            self._view.claims.dialog = None
            if answer is None:
                self._send(
                    DecideClaimed(
                        cast_id=request.cast_id,
                        request_id=request.request_id,
                        claim_id=None,
                    )
                )
            else:
                self._resolve(request, answer)

        self.push_screen(dialog, answered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        typed = event.value.strip()
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
            self.say(f"{typed!r} means nothing here — {_HINT}")
        self.changed()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str]) -> None:
        if (key := event.node.data) != self._view.drawn.cursor:
            self._view.drawn.cursor = key
            self._view.arming = None
        self.changed()

    def _answer(self, typed: str) -> None:
        if (found := self._waiting()) is None:
            self.say(_NOTHING_WAITING)
            return
        _, request = found
        if (
            refused := send_answer(request=request, typed=typed, send=self._send)
        ) is not None:
            self.say(refused)

    def _entry(self) -> Entry | None:
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

    def _resolve(self, request: DecideRequested, answer: str) -> None:
        self._send(
            DecideResolved(
                cast_id=request.cast_id, request_id=request.request_id, answer=answer
            )
        )

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
            if view.status in {"running", "queued"}
            or view.hello.project_root not in self._view.branches
        }
        found = await asyncio.gather(*(self._branch_of(root) for root in roots))
        self._view.branches.update(zip(roots, found, strict=True))
        self.changed()

    # A failed cast counts, and stays in the running-only contents, until it
    # has been on the page and the cursor has moved off it: gone the moment it
    # was opened, it would leave the line under the cursor as it was read.
    # Judged a repaint apart, because a rebuilt tree's cursor passes over the
    # first line on its way back to where it was.
    def _open(self, entry: Entry | None) -> None:
        shown = self._view.shown
        opened = None if entry is None or entry.view is None else entry.view
        cast_id = None if opened is None else opened.hello.cast_id
        if shown.opened is not None and shown.opened != cast_id:
            shown.seen.add(shown.opened)
        shown.opened = cast_id

    def _repaint(self) -> None:
        # A tick can land while the app is closing and its widgets are gone.
        if not self._view.dirty or not self._w.contents.is_mounted:
            return
        self._view.dirty = False
        listed = self._listed()
        now = datetime.now(UTC)
        where = "all projects" if self._scope.every else named(self._scope.home)
        self.sub_title = f"{counted(listed) or 'no casts'}  ({where})"
        self._open(self._entry())
        self._paint_contents(listed, now)
        entry = self._entry()
        self._paint_ask(listed, self._focused())
        self._w.head.update(
            head(entry, casts=self._casts.casts, branches=self._view.branches, now=now)
        )
        self._paint_output(entry)
        self._close_answered()

    # Rebuilt only when a line comes or goes, relabelled otherwise, so the
    # cursor stays on the line the operator put it on. When its line goes, the
    # cursor goes to the nearest line above it that is still there; with none,
    # to the first cast, which is what a window opens to look at.
    def _paint_contents(self, listed: list[CastView], now: datetime) -> None:
        drawn = self._view.drawn
        lines = walked(
            contents(
                listed,
                everything=self._view.shown.everything,
                folded=self._view.shown.folded,
                seen=self._view.shown.seen,
            )
        )
        drawn.entries = {entry.key: entry for entry, _ in lines}
        shape = tuple((entry.key, parent, bool(entry.shown)) for entry, parent in lines)
        if shape == drawn.shape:
            for key, node in drawn.nodes.items():
                node.set_label(line_text(drawn.entries[key], now))
            return
        tree = self._w.contents
        tree.clear()
        drawn.nodes = {}
        for entry, parent in lines:
            under = drawn.nodes[parent] if parent is not None else tree.root
            text = line_text(entry, now)
            drawn.nodes[entry.key] = (
                under.add(text, data=entry.key, expand=True)
                if entry.shown
                else under.add_leaf(text, data=entry.key)
            )
        cursor = self._kept(self._view.drawn.cursor)
        drawn.shape = shape
        drawn.parents = {entry.key: parent for entry, parent in lines}
        if cursor is None and lines:
            casts = [entry.key for entry, _ in lines if entry.kind == "cast"]
            cursor = casts[0] if casts else lines[0][0].key
        self._view.drawn.cursor = cursor
        # A node has no line until the tree has laid it out, and the cursor
        # the rebuild left on the first line says so on its way.
        if cursor is not None:
            tree.call_after_refresh(tree.move_cursor, drawn.nodes[cursor])

    # Up the chain of lines it hung under, no longer than the chain itself, so
    # a parent map that loops still ends.
    def _kept(self, key: str | None) -> str | None:
        drawn = self._view.drawn
        for _ in range(len(drawn.parents) + 1):
            if key is None or key in drawn.nodes:
                return key
            key = drawn.parents.get(key)
        return None

    # Loud while the cast in view waits on the operator, and a pointer to the
    # next one while some other cast does: a question nobody sees is a cast
    # that never ends.
    def _paint_ask(self, listed: list[CastView], view: CastView | None) -> None:
        ask = self._w.ask
        text = ""
        if view is not None and view.waiting:
            prompt = next(iter(view.waiting.values()))
            request = prompt.request
            allowed = allowed_answers(options=request.options, free=request.free)
            takes = " | ".join(allowed) if allowed is not None else "any answer"
            holds = holder(view, prompt, self._view.claims.mine)
            text = f"⏸ {request.prompt}\n  {takes} · {holds} · t answers it"
        elif waiting := [other for other in listed if other.waiting]:
            many = "1 cast waits" if len(waiting) == 1 else f"{len(waiting)} casts wait"
            text = f"⏸ {many} on you · w goes to it"
        ask.display = bool(text)
        ask.update(text)

    # Rewritten only when it changed. It follows the newest line unless the
    # operator scrolled up off where it last left it, and keeps following when
    # the page above it grows and pushes the end further down.
    def _paint_output(self, entry: Entry | None) -> None:
        log, follow = self._w.log, self._view.follow
        if (page := None if entry is None else entry.key) != follow.page:
            follow.page, follow.on = page, True
        elif log.is_vertical_scroll_end:
            follow.on = True
        elif log.scroll_y < follow.at:
            follow.on = False
        lines = output(entry)
        if list(log.lines) != lines:
            log.auto_scroll = False
            log.clear()
            log.write_lines(lines)
        if follow.on:
            log.call_after_refresh(self._to_end)

    def _to_end(self) -> None:
        log = self._w.log
        log.scroll_end(animate=False, immediate=True)
        self._view.follow.at = log.max_scroll_y

    # A prompt answered or withdrawn while its dialog is up closes the dialog:
    # nobody is waiting on what it would send. The command palette, the one
    # screen that can be open over it, is popped first and at once: `dismiss`
    # pops whatever is on top.
    def _close_answered(self) -> None:
        if (dialog := self._view.claims.dialog) is None or any(
            dialog.request_id in view.waiting for view in self._casts.casts.values()
        ):
            return
        self._view.claims.dialog = None
        if isinstance(self.screen, CommandPalette):
            self.pop_screen()
        dialog.dismiss(None)
