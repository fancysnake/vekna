from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import uuid4

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.markup import escape
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Input, Static
from typing_extensions import override

from vekna.pacts.casts import Casts, CastView, Prompt
from vekna.wire import (
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    WireMessage,
    allowed_answers,
)

from .dashboard import CAST_USAGE, cast_request
from .screen import (
    counted,
    drilled,
    elapsed,
    named,
    now_doing,
    ordered,
    scoped,
    steps_done,
    word,
)

_COLUMNS = (
    "#",
    "cast",
    "ritual",
    "project",
    "status",
    "elapsed",
    "steps",
    "branch",
    "where",
    "now",
)
_ID = 8
# All the output the view holds for a rite: the pane scrolls.
_TAIL = 200
_COALESCE_SECONDS = 0.1
_TICK_SECONDS = 1.0
_BRANCH_SECONDS = 3.0
_HINT = "c <ritual> --flag v · a <answer> · t take over · g/p scope · q quit"
_EVERY = "all projects"
_NOTHING_WAITING = "nothing to answer — pick a waiting cast first"


def _where(root: str) -> str:
    home = str(Path.home())
    return f"~{root[len(home):]}" if root.startswith(home) else root


# Who answers a prompt, as this window sees it: a claim id it minted is its own.
def _holder(view: CastView, prompt: Prompt, mine: set[str]) -> str:
    if prompt.claim_id is None:
        return "asked at its terminal" if not view.hello.wired else "open"
    return "taken over here" if prompt.claim_id in mine else "claimed elsewhere"


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
        self._choices = list(allowed or request.options or [])
        self._free = allowed is None

    @override
    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(f"{self._label}\n\n{self._request.prompt}", markup=False)
            with Horizontal(id="options"):
                for index, choice in enumerate(self._choices):
                    yield Button(escape(choice), id=f"choice-{index}")
            if self._free:
                yield Input(placeholder="answer in your own words", id="free")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        index = int((event.button.id or "choice-0").removeprefix("choice-"))
        self.dismiss(self._choices[index])

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.dismiss(event.value)

    def action_let_go(self) -> None:
        self.dismiss(None)


# What the window is showing and what it has done: the scope, the cast under
# the cursor, whether it needs repainting, the claims it made, the branch each
# tree was last seen on, and the prompt its dialog is answering.
@dataclass
class _View:
    every: bool = False
    focus: str | None = None
    dirty: bool = True
    mine: set[str] = field(default_factory=set)
    branches: dict[str, str | None] = field(default_factory=dict)
    answering: str | None = None


# The daemon's casts in a table, the one under the cursor in the pane beside it,
# and a line at the bottom to start a cast or answer one. What it reads and how
# it paints the rite tree are the line view's; what it adds is a screen that
# redraws in place, so typing is never painted over, and prompts answered in a
# dialog of their own.
class VeknaApp(App[None]):
    TITLE = "vekna"
    CSS = """
    #body { height: 1fr; }
    #casts { width: 3fr; }
    #pane { width: 2fr; border-left: solid $panel; }
    #note { height: auto; color: $warning; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "quit"),
        Binding("c", "command('c ')", "cast"),
        Binding("a", "command('a ')", "answer"),
        Binding("t", "take", "take over"),
        Binding("g", "every", "every project"),
        Binding("p", "home", "this project"),
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
        self._home = project
        self._root = root
        self._send = send
        self._branch_of = branch_of
        self._view = _View()

    @override
    def compose(self) -> ComposeResult:
        with Horizontal(id="body"):
            yield DataTable(id="casts", cursor_type="row", zebra_stripes=True)
            with VerticalScroll(id="pane"):
                yield Static(id="detail", markup=False)
        yield Static(id="note", markup=False)
        yield Input(placeholder=_HINT, id="command", select_on_focus=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#casts", DataTable)
        for column in _COLUMNS:
            table.add_column(column, key=column)
        table.focus()
        self.set_interval(_COALESCE_SECONDS, self._repaint)
        self.set_interval(_TICK_SECONDS, self.changed)
        self.set_interval(_BRANCH_SECONDS, self._look_up_branches)
        self.call_later(self._look_up_branches)

    def changed(self) -> None:
        self._view.dirty = True

    def say(self, note: str) -> None:
        self.query_one("#note", Static).update(note)

    # --- what the operator does ---

    def action_command(self, prefix: str) -> None:
        line = self.query_one("#command", Input)
        line.value = prefix
        line.cursor_position = len(prefix)
        line.focus()

    def action_every(self) -> None:
        self._view.every = True
        self.changed()

    def action_home(self) -> None:
        self._view.every = False
        self.changed()

    # The oldest open prompt of the cast under the cursor, claimed so whoever
    # else was answering it stops, then asked in a dialog.
    def action_take(self) -> None:
        if (found := self._waiting()) is None:
            self.say(_NOTHING_WAITING)
            return
        view, request = found
        self._claim(request)
        self._view.answering = request.request_id
        label = f"{view.hello.ritual} {view.hello.cast_id[:_ID]}"

        def answered(answer: str | None) -> None:
            self._view.answering = None
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

        self.push_screen(AnswerScreen(label=label, request=request), answered)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        typed = event.value.strip()
        event.input.value = ""
        self.query_one("#casts", DataTable).focus()
        if typed.lower() in {"q", "quit"}:
            self.exit()
        elif typed.lower() in {"g", "p"}:
            self._view.every = typed.lower() == "g"
        elif typed.lower() == "t":
            self.action_take()
        elif typed.lower().startswith("c "):
            self._cast(typed[2:])
        elif typed.lower().startswith("a "):
            self._answer(typed[2:].strip())
        elif typed:
            self.say(f"{typed!r} means nothing here — {_HINT}")
        self.changed()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._view.focus = event.row_key.value
        self.changed()

    def _cast(self, typed: str) -> None:
        try:
            request = cast_request(typed, root=self._root)
        except ValueError as error:
            self.say(f"{CAST_USAGE} — {error}")
            return
        self._send(request)
        self.say(f"asked for {request.ritual}")

    def _answer(self, answer: str) -> None:
        if (found := self._waiting()) is None:
            self.say(_NOTHING_WAITING)
            return
        _, request = found
        allowed = allowed_answers(options=request.options, free=request.free)
        if allowed is not None and answer not in allowed:
            self.say(f"{answer!r} is not one of {', '.join(allowed)}")
            return
        self._claim(request)
        self._resolve(request, answer)

    def _waiting(self) -> tuple[CastView, DecideRequested] | None:
        view = (
            None
            if self._view.focus is None
            else self._casts.casts.get(self._view.focus)
        )
        if view is None or not view.waiting:
            return None
        return view, next(iter(view.waiting.values())).request

    def _claim(self, request: DecideRequested) -> None:
        claim_id = uuid4().hex
        self._view.mine.add(claim_id)
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
        project = None if self._view.every else self._home
        return ordered(scoped(list(self._casts.casts.values()), project))

    async def _look_up_branches(self) -> None:
        roots = {
            view.hello.project_root
            for view in self._listed()
            if view.status in {"running", "queued"}
            or view.hello.project_root not in self._view.branches
        }
        for root in roots:
            self._view.branches[root] = await self._branch_of(root)
        self.changed()

    def _repaint(self) -> None:
        if not self._view.dirty:
            return
        self._view.dirty = False
        listed = self._listed()
        now = datetime.now(UTC)
        where = _EVERY if self._view.every else named(self._home)
        self.sub_title = f"{counted(listed) or 'no casts'}  ({where})"
        self._paint_table(listed, now)
        self._paint_pane(now)
        self._close_answered()

    def _paint_table(self, listed: list[CastView], now: datetime) -> None:
        table = self.query_one("#casts", DataTable)
        rows = [self._row(index, view, now) for index, view in enumerate(listed, 1)]
        keys = [view.hello.cast_id for view in listed]
        if [key.value for key in table.rows] != keys:
            table.clear()
            for key, row in zip(keys, rows, strict=True):
                table.add_row(*row, key=key)
            if self._view.focus in keys:
                table.move_cursor(row=keys.index(self._view.focus))
            return
        for key, row in zip(keys, rows, strict=True):
            for column, cell in zip(_COLUMNS, row, strict=True):
                table.update_cell(key, column, cell)

    def _row(self, index: int, view: CastView, now: datetime) -> tuple[str, ...]:
        root = view.hello.project_root
        cells = (
            str(index),
            view.hello.cast_id[:_ID],
            view.hello.ritual,
            named(view.hello.project),
            word(view),
            elapsed(view, now),
            str(steps_done(view)),
            self._view.branches.get(root) or "—",
            _where(root),
            now_doing(view, now),
        )
        return tuple(escape(cell) for cell in cells)

    def _paint_pane(self, now: datetime) -> None:
        detail = self.query_one("#detail", Static)
        view = (
            None
            if self._view.focus is None
            else self._casts.casts.get(self._view.focus)
        )
        if view is None:
            detail.update("no cast under the cursor — `c <ritual>` starts one")
            return
        root = view.hello.project_root
        mine = self._view.mine
        lines = [
            *drilled(view, now, tail=_TAIL),
            f" branch {self._view.branches.get(root) or '—'} · in {root}",
            *(
                f" ⏸ {prompt.request.prompt} — {_holder(view, prompt, mine)};"
                " t answers it here"
                for prompt in view.waiting.values()
            ),
        ]
        detail.update("\n".join(lines))

    # A prompt answered or withdrawn while its dialog is up closes the dialog:
    # nobody is waiting on what it would send.
    def _close_answered(self) -> None:
        if self._view.answering is None:
            return
        still = any(
            self._view.answering in view.waiting for view in self._casts.casts.values()
        )
        if not still:
            self._view.answering = None
            self.pop_screen()
