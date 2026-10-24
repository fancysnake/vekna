import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Log, Static, Tree
from textual.widgets.tree import TreeNode
from typing_extensions import override

from vekna.pacts.casts import Casts, CastView, Prompt, RiteStatus, RiteView
from vekna.wire import (
    CastCancelRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    WireMessage,
    allowed_answers,
)

from .cast_text import carried, clock, counted, elapsed, named, word
from .commands import request_cast, send_answer
from .screen import ordered, scoped

_ID = 8
# The list is a narrow column beside the cast it opens: a name that does not
# fit is cut rather than pushing the window sideways.
_NAME = 24
_COALESCE_SECONDS = 0.1
_TICK_SECONDS = 1.0
_BRANCH_SECONDS = 3.0
_HINT = "c <ritual> --flag v · a <answer> · t take over · g/p scope · q quit"
_NOTHING_WAITING = "nothing to answer — pick a waiting cast first"
_NO_CAST = "no cast under the cursor — c starts one"
# The glyph and its colour carry the status, so the list needs no column for
# the word; a waiting cast is the loudest thing on screen because it is the
# one that cannot go on without the operator.
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
_WAITING_LOOK = "bold yellow"


def _where(root: str) -> str:
    path, home = Path(root), Path.home()
    return str(Path("~", path.relative_to(home))) if path.is_relative_to(home) else root


def _first(text: str) -> str:
    return next(iter(text.splitlines()), "")


def _cut(text: str, width: int) -> str:
    return f"{text[: width - 1]}…" if len(text) > width else text


# Who answers a prompt, as this window sees it: a claim id it minted is its own.
def _holder(view: CastView, prompt: Prompt, mine: set[str]) -> str:
    if prompt.claim_id is None:
        return "asked at its terminal" if not view.hello.wired else "open"
    return "taken over here" if prompt.claim_id in mine else "claimed elsewhere"


# Each cast under the one that queued it, so a hand cast reads as the tree of
# casts it set going. A cast whose parent is out of view stands on its own, and
# the `seen` guard keeps a chain that loops back on itself from vanishing.
def nested(listed: list[CastView]) -> list[tuple[int, CastView]]:
    ids = {view.hello.cast_id for view in listed}
    children: dict[str, list[CastView]] = {}
    for view in listed:
        if (parent := view.hello.enqueued_by) in ids:
            children.setdefault(parent or "", []).append(view)
    rows: list[tuple[int, CastView]] = []
    seen: set[str] = set()

    def walk(view: CastView, depth: int) -> None:
        if view.hello.cast_id in seen:
            return
        seen.add(view.hello.cast_id)
        rows.append((depth, view))
        for child in children.get(view.hello.cast_id, []):
            walk(child, depth + 1)

    for view in listed:
        if view.hello.enqueued_by not in ids:
            walk(view, 0)
    for view in listed:
        walk(view, 0)
    return rows


def _rite_label(rite: RiteView, now: datetime) -> Text:
    until = rite.finished_at or now
    took = clock((until - rite.started.started_at).total_seconds())
    medium = "italic" if rite.started.category == "medium" else ""
    label = Text.assemble(
        _RITE_LOOK[rite.status], " ", (rite.started.name, medium), (f"  {took}", "dim")
    )
    if rite.error is not None:
        label.append(f"  {_first(rite.error)}", style="red")
    return label


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


# The shape of the rite tree last drawn, and a node per rite in it.
@dataclass
class _Drawn:
    shape: tuple[str, ...] = ()
    nodes: dict[str, TreeNode[str | None]] = field(default_factory=dict)


# What the window is showing and what it has done: the cast and the rite under
# the cursor, whether it needs repainting, the cast one more x cancels, the
# branch each tree was last seen on, its claims, and the rite tree drawn.
@dataclass
class _View:
    focus: str | None = None
    rite: str | None = None
    dirty: bool = True
    arming: str | None = None
    branches: dict[str, str | None] = field(default_factory=dict)
    claims: _Claims = field(default_factory=_Claims)
    drawn: _Drawn = field(default_factory=_Drawn)


# Held rather than queried: `query_one` searches whichever screen is on top,
# which is the answer dialog while one is up.
@dataclass
class _Widgets:
    casts: DataTable[Text] = field(
        default_factory=lambda: DataTable(
            id="casts", cursor_type="row", show_header=False
        )
    )
    ask: Static = field(default_factory=lambda: Static(id="ask", markup=False))
    head: Static = field(default_factory=lambda: Static(id="head", markup=False))
    rites: Tree[str | None] = field(
        default_factory=lambda: Tree[str | None]("rites", id="rites")
    )
    log: Log = field(default_factory=lambda: Log(id="log"))
    note: Static = field(default_factory=lambda: Static(id="note", markup=False))
    command: Input = field(
        default_factory=lambda: Input(
            placeholder=_HINT, id="command", select_on_focus=False
        )
    )


# The daemon's casts as a narrow tree on the left; the one under the cursor on
# the right as a banner when it is waiting on the operator, a line saying where
# it runs, the tree of its rites, and the output of the rite picked in that
# tree. The command line shows only while it is being typed into.
class VeknaApp(App[None]):
    TITLE = "vekna"
    CSS = """
    #body { height: 1fr; }
    #casts { width: 42; max-width: 50%; border: round $panel; }
    #side { width: 1fr; }
    #ask {
        display: none; height: auto; padding: 0 1;
        background: $warning 25%; text-style: bold;
    }
    #head { height: auto; padding: 0 1; }
    #rites { height: auto; max-height: 50%; border: round $panel; }
    #log { height: 1fr; border: round $panel; }
    #casts:focus, #rites:focus { border: round $accent; }
    #note { height: auto; padding: 0 1; color: $warning; }
    #command { display: none; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "quit"),
        Binding("c", "command('c ')", "cast"),
        Binding("t", "take", "answer"),
        Binding("w", "next_waiting", "next waiting"),
        Binding("x", "cancel", "cancel"),
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
        with Horizontal(id="body"):
            yield self._w.casts
            with Vertical(id="side"):
                yield self._w.ask
                yield self._w.head
                yield self._w.rites
                yield self._w.log
        yield self._w.note
        yield self._w.command
        yield Footer()

    def on_mount(self) -> None:
        table = self._w.casts
        table.add_column("", key="status", width=1)
        table.add_column("cast", key="cast", width=_NAME)
        table.add_column("elapsed", key="elapsed", width=7)
        table.border_title = "casts"
        rites = self._w.rites
        rites.show_root = False
        rites.border_title = "rites"
        self._w.log.border_title = "output"
        table.focus()
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
        self._w.casts.focus()

    def action_every(self) -> None:
        self._scope.every = True
        self.changed()

    def action_home(self) -> None:
        self._scope.every = False
        self.changed()

    # The cursor onto the next cast down that is waiting on the operator,
    # wrapping round to the top.
    def action_next_waiting(self) -> None:
        table = self._w.casts
        keys = [key.value for key in table.rows]
        start = keys.index(self._view.focus) + 1 if self._view.focus in keys else 0
        for index in list(range(start, len(keys))) + list(range(start)):
            view = self._casts.casts.get(keys[index] or "")
            if view is not None and view.waiting:
                table.move_cursor(row=index)
                return
        self.say("no cast is waiting on you")

    # Twice, on the same cast: the first x says what the second one does.
    def action_cancel(self) -> None:
        view = self._focused()
        if view is None or view.status != "running":
            self._view.arming = None
            self.say("only a running cast can be cancelled")
            return
        named_cast = f"{view.hello.ritual} {view.hello.cast_id[:_ID]}"
        if self._view.arming != view.hello.cast_id:
            self._view.arming = view.hello.cast_id
            self.say(f"x again cancels {named_cast}")
            return
        self._view.arming = None
        self._send(CastCancelRequested(cast_id=view.hello.cast_id))
        self.say(f"asked {named_cast} to stop")

    # The oldest open prompt of the cast under the cursor, claimed so whoever
    # else was answering it stops, then asked in a dialog.
    def action_take(self) -> None:
        if (found := self._waiting()) is None:
            self.say(_NOTHING_WAITING)
            return
        view, request = found
        self._claim(request)
        dialog = AnswerScreen(
            label=f"{view.hello.ritual} {view.hello.cast_id[:_ID]}", request=request
        )
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

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value != self._view.focus:
            self._view.focus = event.row_key.value
            self._view.rite = None
            self._view.arming = None
        self.changed()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted[str | None]) -> None:
        self._view.rite = event.node.data
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

    def _focused(self) -> CastView | None:
        if self._view.focus is None:
            return None
        return self._casts.casts.get(self._view.focus)

    def _waiting(self) -> tuple[CastView, DecideRequested] | None:
        view = self._focused()
        if view is None or not view.waiting:
            return None
        return view, next(iter(view.waiting.values())).request

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

    def _repaint(self) -> None:
        # A tick can land while the app is closing and its widgets are gone.
        if not self._view.dirty or not self._w.casts.is_mounted:
            return
        self._view.dirty = False
        listed = self._listed()
        now = datetime.now(UTC)
        where = "all projects" if self._scope.every else named(self._scope.home)
        self.sub_title = f"{counted(listed) or 'no casts'}  ({where})"
        self._paint_table(nested(listed), now)
        view = self._focused()
        self._paint_ask(listed, view)
        self._paint_head(view, now)
        self._paint_rites(view, now)
        self._paint_output(view)
        self._close_answered()

    def _paint_table(self, rows: list[tuple[int, CastView]], now: datetime) -> None:
        table = self._w.casts
        cells = [self._row(depth, view, now) for depth, view in rows]
        keys = [view.hello.cast_id for _, view in rows]
        if [key.value for key in table.rows] != keys:
            table.clear()
            for key, row in zip(keys, cells, strict=True):
                table.add_row(*row, key=key)
            if self._view.focus in keys:
                table.move_cursor(row=keys.index(self._view.focus))
            else:
                # The cursor lands on the top row; the pane follows it in this
                # same repaint rather than on the highlight event after it.
                self._view.focus = keys[0] if keys else None
                self._view.rite = self._view.arming = None
            return
        for key, row in zip(keys, cells, strict=True):
            for column, cell in zip(("status", "cast", "elapsed"), row, strict=True):
                table.update_cell(key, column, cell)

    def _row(self, depth: int, view: CastView, now: datetime) -> tuple[Text, ...]:
        name = view.hello.ritual
        if self._scope.every:
            name = f"{named(view.hello.project)}:{name}"
        indent = "  " * (depth - 1) + "└ " if depth else ""
        label = Text(_cut(indent + name, _NAME))
        if view.waiting:
            label.stylize(_WAITING_LOOK)
        return (
            _CAST_LOOK[word(view)].copy(),
            label,
            Text(elapsed(view, now), style="dim", justify="right"),
        )

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
            holder = _holder(view, prompt, self._view.claims.mine)
            text = f"⏸ {request.prompt}\n  {takes} · {holder} · t answers it"
        elif waiting := [other for other in listed if other.waiting]:
            many = "1 cast waits" if len(waiting) == 1 else f"{len(waiting)} casts wait"
            text = f"⏸ {many} on you · w goes to it"
        ask.display = bool(text)
        ask.update(text)

    def _paint_head(self, view: CastView | None, now: datetime) -> None:
        head = self._w.head
        if view is None:
            head.update(_NO_CAST)
            return
        hello = view.hello
        root = hello.project_root
        branch = self._view.branches.get(root) or "—"
        status = f"{word(view)}  {elapsed(view, now)}{carried(hello)}"
        lines = [
            f"{hello.ritual}  {hello.cast_id[:_ID]}  {status}",
            f"{branch} · {_where(root)}",
        ]
        if view.blocked is not None:
            lines.append(
                f"tree {view.blocked.path} left blocked: {view.blocked.reason}"
            )
        head.update("\n".join(lines))

    # Rebuilt only when a rite or prompt comes or goes, relabelled otherwise,
    # so the cursor stays on the node the operator put it on.
    def _paint_rites(self, view: CastView | None, now: datetime) -> None:
        tree = self._w.rites
        if view is None:
            shape: tuple[str, ...] = ()
        else:
            shape = (view.hello.cast_id, *view.rites, *view.waiting)
        if shape == self._view.drawn.shape:
            if view is not None:
                for rite_id, node in self._view.drawn.nodes.items():
                    node.set_label(_rite_label(view.rites[rite_id], now))
            return
        self._view.drawn.shape = shape
        tree.clear()
        self._view.drawn.nodes = {}
        if view is not None:
            self._grow(tree, view, now)

    def _grow(self, tree: Tree[str | None], view: CastView, now: datetime) -> None:
        nodes = self._view.drawn.nodes
        parents = {rite.started.parent_id for rite in view.rites.values()} | {
            prompt.request.rite_id for prompt in view.waiting.values()
        }
        # Begin order puts each parent before its children; one a peer named
        # out of order hangs off the root rather than going missing.
        for rite_id, rite in view.rites.items():
            parent = nodes.get(rite.started.parent_id or "", tree.root)
            label = _rite_label(rite, now)
            nodes[rite_id] = (
                parent.add(label, data=rite_id, expand=True)
                if rite_id in parents
                else parent.add_leaf(label, data=rite_id)
            )
        for prompt in view.waiting.values():
            request = prompt.request
            parent = nodes.get(request.rite_id or "", tree.root)
            label = Text(f"⏸ {_first(request.prompt)}", style=_WAITING_LOOK)
            parent.add_leaf(label, data=request.rite_id)
        if self._view.rite in nodes:
            tree.move_cursor(nodes[self._view.rite])

    # The rite picked in the tree, or else the latest one still talking, or
    # else the last one that said anything. Why the cast ended follows it.
    def _paint_output(self, view: CastView | None) -> None:
        log = self._w.log
        rite = None if view is None else self._shown_rite(view)
        lines = [] if rite is None else list(rite.deltas)
        if (
            view is not None
            and view.detail
            and view.status not in {"running", "queued"}
        ):
            lines += ["", *view.detail.splitlines()]
        log.border_title = "output" if rite is None else f"output · {rite.started.name}"
        # Rewritten only when it changed, and kept at the tail only when the
        # operator had not scrolled up off it.
        if list(log.lines) != lines:
            log.auto_scroll = log.is_vertical_scroll_end
            log.clear()
            log.write_lines(lines)

    def _shown_rite(self, view: CastView) -> RiteView | None:
        if self._view.rite in view.rites:
            return view.rites[self._view.rite or ""]
        rites = list(view.rites.values())
        talking = [rite for rite in rites if rite.status == "running" and rite.deltas]
        said = talking or [rite for rite in rites if rite.deltas]
        return said[-1] if said else None

    # A prompt answered or withdrawn while its dialog is up closes the dialog:
    # nobody is waiting on what it would send. Whatever is open over it, the
    # command palette, goes with it, or `dismiss` would pop that instead.
    def _close_answered(self) -> None:
        if (dialog := self._view.claims.dialog) is None or any(
            dialog.request_id in view.waiting for view in self._casts.casts.values()
        ):
            return
        self._view.claims.dialog = None
        # A `while` in disguise: pylint's `while_used` bans the statement.
        for _ in itertools.takewhile(lambda _: not dialog.is_active, itertools.count()):
            self.screen.dismiss()
        dialog.dismiss(None)
