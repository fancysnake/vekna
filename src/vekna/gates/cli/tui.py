import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import ClassVar, Protocol
from uuid import uuid4

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static, Tree
from textual.widgets.tree import TreeNode
from typing_extensions import override

from vekna.pacts.casts import Casts, CastView, checkout, named
from vekna.wire import (
    CastCancelRequested,
    CastSeen,
    DecideClaimed,
    DecideReleased,
    DecideRequested,
    WireMessage,
)

from .cast_text import clock, counted, labelled, live, top_prompt
from .commands import request_cast, send_answer
from .contents import (
    Entry,
    Reading,
    cast_key,
    contents,
    fitted,
    folded_all,
    historic,
    walked,
)
from .page import LEAVES, head, holder, line_text, output, taken_head, taken_output
from .pane import Output
from .screen import ordered, scoped

_COALESCE_SECONDS = 0.1
# The least a Textual tree takes: the contents page is narrow, and what a line
# says is worth more of it than the lines that join it to its parent.
_GUIDE_DEPTH = 2
_TICK_SECONDS = 1.0
_BRANCH_SECONDS = 3.0
# How often the window reads its config again, so an edit counts within this.
_CONFIG_SECONDS = 5.0
# shortcut: a replay is taken as over when no cast came or ended for this
# long, since the wire has no message that ends one; add one when it does.
_SETTLE_SECONDS = 0.3
# A tree that casts keep changing is still drawn: the question line and the
# output must not wait on a daemon that never goes quiet.
_FIT_WAIT_SECONDS = 2.0
_NOTHING_WAITING = "nothing to answer — pick a waiting cast first"
_ASKS_NOTHING = "the cast asks nothing right now"
_NOTHING_TO_MARK = "only a failed cast can be marked seen"
_NOTHING_TO_TAKE = "only a running cast can be taken over"
_ANSWER_HERE = "answer here"
_TYPE_FIRST = "type an answer first"
_QUESTION_CHANGED = "the question changed — your answer was not sent"
_VIGILS_SECONDS = 3.0
_VIGILS_PAUSED = "vigils paused — what runs carries on, and v lets them cast again"
_VIGILS_CAST = "vigils cast again"
_VIGILS_UNSAID = (
    "the daemon did not say whether its vigils are paused: it is gone, or it"
    " predates pausing them"
)


# `old` is how many ended casts the history view holds.
def _hint(old: int = 0, *, every: bool = False) -> str:
    return (
        f"space open/fold · f fold all · H history{f' ({old})' if old else ''}"
        " · w next asking · t take over · x cancel · s seen · : command"
        f" · g/p scope{' · enter show alone' if every else ''} · q quit"
    )


def _taken_hint(view: CastView) -> str:
    return (
        f"taken over {labelled(view.hello)} · enter answers"
        f" · {LEAVES} and hands the prompts back"
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
        Binding("enter", "app.open", "show alone", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("h", "cursor_parent", show=False),
    ]


class _SetVigilsPaused(Protocol):
    async def __call__(self, *, paused: bool) -> bool | None: ...


# What the window says to the daemon: frames down its own connection, and a
# mark or the vigils' pause on a connection of its own. `mark` answers why the
# daemon refused it. `vigils_paused` asks whether the vigils are paused and
# `set_vigils_paused` pauses them or lets them cast again; both answer whether
# they are paused, or `None` when the daemon did not say.
@dataclass(frozen=True)
class ToDaemon:
    send: Callable[[WireMessage], None]
    mark: Callable[[CastSeen], Awaitable[str | None]]
    vigils_paused: Callable[[], Awaitable[bool | None]]
    set_vigils_paused: _SetVigilsPaused


# What the window reads that the daemon does not send it: the branch a tree is
# on, and its own config as it reads now, which is how long after it ended a
# cast moves to the history view and what would not read.
@dataclass(frozen=True)
class Outside:
    branch_of: Callable[[str], Awaitable[str | None]]
    history_after: Callable[[], Awaitable[tuple[timedelta, str]]]


# What a window is opened with: its project, the directory a ritual started
# from it runs in while it is on that project, how long after it ended a cast
# moves to the history view, what its config said that would not read, the
# title it shows: the versions of this vekna and
# of its daemon, and how long a cast taken over may ask nothing after an answer
# before it is left, and whether a tree is folded to fit the window's height:
# the first it draws, and the one it draws when it turns to every project or
# back to one.
@dataclass(frozen=True)
class Opened:
    project: str
    root: str
    history_after: timedelta
    ignored: str = ""
    title: str = "vekna"
    quiet: timedelta = timedelta(seconds=5)
    fit: bool = False


# What the window opened with, the project it is on and the directory a ritual
# started from it runs in, whether it shows every project instead of that one,
# and whether the next tree it draws is to be folded to fit its height. A tree
# is fitted to casts that have stopped arriving: `seen` is how many there are
# and how many of them run, and `seen_at` when that last changed. Until then
# the contents are not drawn, so a daemon replaying its casts does not show
# each of them come and end. It waits at most `_FIT_WAIT_SECONDS` from when the
# fit was asked for.
@dataclass
class _Scope:
    opened: Opened
    project: str = field(init=False)
    every: bool = False
    to_fit: bool = field(init=False)
    seen: tuple[int, int] = (0, 0)
    seen_at: float = field(default_factory=monotonic)
    fit_asked_at: float = field(default_factory=monotonic)

    def __post_init__(self) -> None:
        self.project = self.opened.project
        self.to_fit = self.opened.fit

    # The window's own project runs a ritual where the window was opened, which
    # may be a worktree or a directory inside the checkout.
    @property
    def root(self) -> str:
        if self.project == self.opened.project:
            return self.opened.root
        return checkout(self.project)

    def turn_to(self, project: str) -> None:
        self.project = project
        self.show(every=False)

    def show(self, *, every: bool) -> None:
        self.every = every
        self.to_fit = self.opened.fit
        self.fit_asked_at = monotonic()

    def settled(self, casts: Casts) -> bool:
        views = casts.casts.values()
        if (seen := (len(views), sum(live(view) for view in views))) != self.seen:
            self.seen, self.seen_at = seen, monotonic()
        at = monotonic()
        return (
            at - self.seen_at >= _SETTLE_SECONDS
            or at - self.fit_asked_at >= _FIT_WAIT_SECONDS
        )


# The claims this window made, the cast it has taken over, and the prompts of
# that cast it claimed. Each is claimed once: a claim another window takes
# after that stays theirs. `draft` is the prompt the answer line was first
# typed into, "" when the cast asked nothing then; none while the line is empty.
# `idle_since` is none until the taken cast got an answer here, then when it
# last had a prompt open; the window's `quiet` seconds later the cast is left.
@dataclass
class _Claims:
    mine: set[str] = field(default_factory=set)
    taken: str | None = None
    asked: set[str] = field(default_factory=set)
    draft: str | None = None
    idle_since: float | None = None


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


# Whether the daemon last said its vigils are paused, and how many times it has
# answered v.
@dataclass
class _Pause:
    paused: bool = False
    answers: int = 0


# What the window last read outside the daemon: the branch each tree was on,
# and what its config said that would not read.
@dataclass
class _Read:
    ignored: str = ""
    branches: dict[str, str | None] = field(default_factory=dict)


# What the window is showing and what it has done: the folds of the contents,
# whether it needs repainting, the cast one more x cancels, what it last read
# outside the daemon, its claims, the contents drawn, and the vigils' pause.
@dataclass
class _View:
    reading: Reading
    read: _Read
    dirty: bool = True
    arming: str | None = None
    claims: _Claims = field(default_factory=_Claims)
    drawn: _Drawn = field(default_factory=_Drawn)
    vigils: _Pause = field(default_factory=_Pause)


# Where a waiting question shows: loud on top for the cast in view, and during
# a takeover one line under the contents for the casts that ask elsewhere. The
# taken cast's own question is in its output, and `answer` under it answers it.
@dataclass
class _Asks:
    answer: Input = field(
        default_factory=lambda: Input(
            id="answer", select_on_focus=False, placeholder=_ANSWER_HERE
        )
    )
    here: Static = field(default_factory=lambda: Static(id="ask", markup=False))
    elsewhere: Static = field(
        default_factory=lambda: Static(id="elsewhere", markup=False)
    )


# The bottom row's lines of text that change: the keys, which casts are listed,
# and that the vigils are paused, shown only while they are.
@dataclass
class _Foot:
    hint: Static = field(default_factory=lambda: Static(_hint(0), id="hint"))
    scope: Static = field(default_factory=lambda: Static(id="scope", markup=False))
    paused: Static = field(
        default_factory=lambda: Static("vigils paused", id="paused", markup=False)
    )


# Held rather than queried, so each widget is reached typed and without a
# lookup. The two question lines are one field: pylint caps a class at seven.
@dataclass
class _Widgets:
    ask: _Asks = field(default_factory=_Asks)
    contents: Contents = field(default_factory=lambda: Contents("all", id="contents"))
    head: Static = field(default_factory=lambda: Static(id="head", markup=False))
    log: Output = field(default_factory=lambda: Output(id="log", auto_scroll=False))
    note: Static = field(default_factory=lambda: Static(id="note", markup=False))
    command: Input = field(
        default_factory=lambda: Input(id="command", select_on_focus=False)
    )
    foot: _Foot = field(default_factory=_Foot)


# A book of the daemon's casts. The left page is the contents: project, ritual,
# its casts newest first, their rites — every cast as one line, a running one
# with `…` and the rite it is on, until space opens its whole rite tree. The
# casts that ended are under the project's `finished`, a streak of casts that
# ended alike as one line. `H`
# turns it to the history view, the casts that ended long ago, by day. The
# right page is the line under the cursor in full, and the output it is making.
# A question waiting anywhere is the loud line on top. The command line shows
# only while it is being typed into. `s` marks a failed cast seen, which takes
# the red off its line and the cast out of every count of fails. `v` pauses the
# daemon's vigils, so that what runs can end before `vekna stop`, and the
# bottom row says so in every window until `v` lets them cast again. `g` shows
# every project and enter on one of them shows it alone: a ritual started from
# the window then runs in that project's checkout. `t` takes a
# cast over: the left page opens its rite tree, the right page is its output,
# every prompt it asks is claimed and shown at the end of that output, and the
# line under the output answers it. The contents take no keys until Esc hands
# the prompts back, or the cast asks nothing more for a while after an answer.
class VeknaApp(App[None]):
    TITLE = "vekna"
    CSS = """
    #ask {
        display: none; height: 1; padding: 0 1;
        background: $warning 25%; text-style: bold;
    }
    #body { height: 1fr; }
    #left { width: 46; max-width: 50%; border-right: vkey $panel; }
    #contents { height: 1fr; padding: 0 1; overflow-x: hidden; }
    #elsewhere { display: none; height: auto; padding: 0 1; color: $warning; }
    #page { width: 1fr; padding: 0 1; }
    #head { height: auto; max-height: 50%; }
    #log { height: 1fr; margin-top: 1; }
    #note { height: auto; padding: 0 1; color: $warning; }
    #command, #answer { display: none; border: none; height: 1; }
    #foot { height: auto; }
    #hint { width: 1fr; padding: 0 1; color: $text-muted; }
    #scope, #version { width: auto; padding: 0 1; color: $text-muted; }
    #paused { display: none; width: auto; padding: 0 1; color: $warning; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "quit"),
        Binding("colon", "command('')", "command"),
        Binding("c", "command('c ')", "cast"),
        Binding("t", "take", "take over"),
        Binding("w", "next_waiting", "next waiting"),
        Binding("x", "cancel", "cancel"),
        Binding("f", "fold_all", "fold all"),
        Binding("s", "seen", "seen"),
        Binding("v", "vigils", "pause vigils"),
        Binding("H", "history", "history"),
        Binding("g", "every", "every project"),
        Binding("p", "home", "this project"),
        Binding("a", "command('a ')", "type an answer", show=False),
        Binding("escape", "close_command", show=False),
    ]

    def __init__(
        self, *, casts: Casts, opened: Opened, daemon: ToDaemon, outside: Outside
    ) -> None:
        super().__init__()
        self._casts = casts
        self._scope = _Scope(opened=opened)
        self._daemon = daemon
        self._outside = outside
        self._view = _View(
            reading=Reading(history_after=opened.history_after),
            read=_Read(ignored=opened.ignored),
        )
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
                yield self._w.ask.answer
        yield self._w.note
        yield self._w.command
        with Horizontal(id="foot"):
            yield self._w.foot.hint
            yield self._w.foot.scope
            yield self._w.foot.paused
            yield Static(self._scope.opened.title, id="version", markup=False)

    def on_mount(self) -> None:
        tree = self._w.contents
        tree.show_root = False
        tree.auto_expand = False
        tree.guide_depth = _GUIDE_DEPTH
        tree.focus()
        self.set_interval(_COALESCE_SECONDS, self._paced)
        self.set_interval(_TICK_SECONDS, self.changed)
        self.set_interval(_BRANCH_SECONDS, self._look_up_branches)
        self.set_interval(_CONFIG_SECONDS, self._read_config)
        self.call_later(self._look_up_branches)
        self.set_interval(_VIGILS_SECONDS, self._look_up_vigils)
        self.call_later(self._look_up_vigils)

    # The keys that move the contents do nothing during a takeover.
    def _locked(self) -> bool:
        return self._view.claims.taken is not None

    def changed(self) -> None:
        self._view.dirty = True

    def say(self, note: str) -> None:
        self._w.note.update(note)

    # --- what the operator does ---

    # A taken-over cast takes answers only, so the key goes to its answer line.
    def action_command(self, prefix: str) -> None:
        if self._view.claims.taken is not None:
            self._w.ask.answer.focus()
            return
        line = self._w.command
        line.display = True
        line.value = prefix
        line.cursor_position = len(prefix)
        line.focus()

    def action_close_command(self) -> None:
        if (view := self._taken()) is not None:
            self._leave(
                view, f"left {labelled(view.hello)} — its prompts are handed back"
            )
            return
        self._close_line()

    def action_every(self) -> None:
        if self._locked():
            return
        self._scope.show(every=True)
        self.changed()

    def action_home(self) -> None:
        if self._locked():
            return
        self._turn_to(self._scope.opened.project)

    # On a project line, the window is on that project as if it had opened
    # there. On any other line enter does nothing.
    def action_open(self) -> None:
        entry = self._entry()
        if self._locked() or entry is None or entry.project is None:
            return
        self._turn_to(entry.project)

    def _turn_to(self, project: str) -> None:
        moved = project != self._scope.project
        self._scope.turn_to(project)
        if moved:
            self.say(f"on {named(project)} · c casts in {self._scope.root}")
        self.changed()

    def action_history(self) -> None:
        if self._locked():
            return
        reading = self._view.reading
        now = datetime.now(UTC)
        if not reading.history and not any(
            historic(view, reading, now) for view in self._listed()
        ):
            after = clock(reading.history_after.total_seconds())
            self.say(f"no history yet — a cast moves there {after} after it ends")
            return
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

    # Every line that holds casts, folded; when they all are, every line back
    # to how it starts.
    def action_fold_all(self) -> None:
        reading = self._view.reading
        reading.toggled = folded_all(
            casts=self._listed(), reading=reading, now=datetime.now(UTC)
        )
        self.changed()

    # The cursor onto the next line down that is waiting on the operator — a
    # cast that asks, or a fold one hides in — wrapping round to the top. The
    # history view never holds a cast that asks, so `w` leaves it for the tree.
    def action_next_waiting(self) -> None:
        if self._locked():
            return
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
            asks = entry.counts["waiting"]
            if asks and (entry.kind == "cast" or entry.folded):
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
        self._daemon.send(CastCancelRequested(cast_id=view.hello.cast_id))
        self.say(f"asked {named_cast} to stop")

    # A failed cast is marked seen, and a seen one unmarked. The daemon keeps
    # the mark and says it to every window, so the line changes when this
    # window hears it.
    async def action_seen(self) -> None:
        view = self._focused()
        if view is None or not view.failed:
            self.say(_NOTHING_TO_MARK)
            return
        seen = not view.seen
        refused = await self._daemon.mark(
            CastSeen(cast_id=view.hello.cast_id, seen=seen)
        )
        named_cast = labelled(view.hello)
        marked = f"marked {named_cast} seen" if seen else f"unmarked {named_cast}"
        self.say(refused or marked)
        self.changed()

    async def action_vigils(self) -> None:
        paused = await self._daemon.set_vigils_paused(
            paused=not self._view.vigils.paused
        )
        if paused is None:
            self.say(_VIGILS_UNSAID)
            return
        self._view.vigils.answers += 1
        self._hear_pause(paused=paused)
        self.say(_VIGILS_PAUSED if paused else _VIGILS_CAST)

    # The cast under the cursor, or the first one that asks under a fold. The
    # line its answers are typed on opens at once, and stays open.
    def action_take(self) -> None:
        if self._locked():
            return
        claims = self._view.claims
        found = self._waiting()
        view = found[0] if found is not None else self._focused()
        if view is None or not live(view):
            self.say(_NOTHING_TO_TAKE)
            return
        claims.taken = view.hello.cast_id
        self._view.reading.kept_open = view.hello.cast_id
        self._w.contents.disabled = True
        self._w.ask.answer.display = True
        self._w.ask.answer.focus()
        self.say(f"took over {labelled(view.hello)}")
        self.changed()

    @on(Input.Changed, "#answer")
    def _typing_answer(self, event: Input.Changed) -> None:
        claims = self._view.claims
        if not event.value:
            claims.draft = None
        elif claims.draft is None:
            claims.draft = self._asking()

    @on(Input.Submitted, "#answer")
    def _submit_answer(self, event: Input.Submitted) -> None:
        claims = self._view.claims
        draft, claims.draft = claims.draft, None
        self._w.ask.answer.value = ""
        if draft is not None and draft != self._asking():
            self.say(_QUESTION_CHANGED)
            return
        if self._answer(event.value.strip(), nothing=_ASKS_NOTHING):
            claims.idle_since = monotonic()

    @on(Input.Submitted, "#command")
    def _submit_command(self, event: Input.Submitted) -> None:
        typed = event.value.strip()
        self.action_close_command()
        if typed.lower() in {"q", "quit"}:
            self.exit()
        elif typed.lower() == "g":
            self.action_every()
        elif typed.lower() == "p":
            self.action_home()
        elif typed.lower() == "t":
            self.action_take()
        elif typed.lower().startswith("c "):
            self.say(
                request_cast(
                    typed=typed[2:], root=self._scope.root, send=self._daemon.send
                )
            )
        elif typed.lower().startswith("a "):
            self._answer(typed[2:].strip(), nothing=_NOTHING_WAITING)
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

    # Whether the answer was sent.
    def _answer(self, typed: str, *, nothing: str) -> bool:
        if (found := self._waiting()) is None:
            self.say(nothing)
            return False
        _, request = found
        if not typed:
            self.say(_TYPE_FIRST)
            return False
        refused = send_answer(request=request, typed=typed, send=self._daemon.send)
        self.say(refused or f"answered {typed}")
        return refused is None

    def _taken(self) -> CastView | None:
        return self._casts.casts.get(self._view.claims.taken or "")

    # The line under the cursor.
    def _entry(self) -> Entry | None:
        return self._view.drawn.entries.get(self._view.drawn.cursor or "")

    # The cast taken over, wherever the cursor was left, else the cast the line
    # under the cursor belongs to: none for a project or a ritual, which hold
    # many.
    def _focused(self) -> CastView | None:
        if (view := self._taken()) is not None:
            return view
        entry = self._entry()
        if entry is None or entry.view is None:
            return None
        return self._casts.casts.get(entry.view.hello.cast_id)

    # The first cast under the cursor that asks, a folded one included: a fold
    # says it asks, so it answers too. A cast taken over is the only one asked.
    def _waiting(self) -> tuple[CastView, DecideRequested] | None:
        casts: tuple[str, ...]
        if (taken := self._taken()) is not None:
            casts = (taken.hello.cast_id,)
        elif (entry := self._entry()) is not None:
            casts = entry.casts
        else:
            return None
        for cast_id in casts:
            view = self._casts.casts.get(cast_id)
            if view is not None and (prompt := top_prompt(view)) is not None:
                return view, prompt.request
        return None

    def _asking(self) -> str:
        found = self._waiting()
        return "" if found is None else found[1].request_id

    def _claim(self, request: DecideRequested) -> None:
        claim_id = uuid4().hex
        self._view.claims.mine.add(claim_id)
        self._daemon.send(
            DecideClaimed(
                cast_id=request.cast_id,
                request_id=request.request_id,
                claim_id=claim_id,
            )
        )

    # Every prompt the taken cast asks is claimed as it comes. A cast that
    # ended has nothing left to hand back. No prompt says it is the last one,
    # so a cast that asks nothing for a while after an answer is left.
    def _hold(self) -> None:
        claims = self._view.claims
        if claims.taken is None:
            return
        view = self._casts.casts[claims.taken]
        if not live(view):
            self._leave(view, "the cast taken over has ended")
            return
        for request_id, prompt in view.waiting.items():
            if request_id not in claims.asked:
                claims.asked.add(request_id)
                self._claim(prompt.request)
        if claims.idle_since is None:
            return
        if view.waiting:
            claims.idle_since = monotonic()
        elif (
            monotonic() - claims.idle_since >= self._scope.opened.quiet.total_seconds()
        ):
            self._leave(view, f"left {labelled(view.hello)} — it asks nothing more")

    # Heard back from the daemon or not, every claim still open goes. A cast
    # that ended waits on nothing, so it has none to hand back.
    def _leave(self, view: CastView, said: str) -> None:
        claims = self._view.claims
        for request_id in claims.asked.intersection(view.waiting):
            self._daemon.send(
                DecideReleased(cast_id=view.hello.cast_id, request_id=request_id)
            )
        claims.taken = None
        claims.asked.clear()
        claims.draft = None
        claims.idle_since = None
        self._view.reading.kept_open = None
        self._w.ask.answer.value = ""
        self._w.ask.answer.display = False
        self._w.contents.disabled = False
        self._close_line()
        self.say(said)
        self.changed()

    def _close_line(self) -> None:
        line = self._w.command
        line.value = ""
        line.display = False
        self._w.contents.focus()

    def _move_to(self, key: str) -> None:
        self._view.drawn.cursor = key
        self._w.contents.move_cursor(self._view.drawn.nodes[key])
        self.changed()

    # --- painting ---

    def _listed(self) -> list[CastView]:
        project = None if self._scope.every else self._scope.project
        return ordered(scoped(list(self._casts.casts.values()), project))

    async def _look_up_branches(self) -> None:
        roots = {
            view.hello.project_root
            for view in self._listed()
            if live(view) or view.hello.project_root not in self._view.read.branches
        }
        found = await asyncio.gather(*(self._outside.branch_of(root) for root in roots))
        self._view.read.branches.update(zip(roots, found, strict=True))
        self.changed()

    # Asked again and again: another window may have paused the vigils, and
    # the daemon tells no window when it does.
    async def _look_up_vigils(self) -> None:
        answers = self._view.vigils.answers
        paused = await self._daemon.vigils_paused()
        # v answered while this look was out: the look may carry the older state.
        if paused is not None and answers == self._view.vigils.answers:
            self._hear_pause(paused=paused)

    def _hear_pause(self, *, paused: bool) -> None:
        self._view.vigils.paused = paused
        self._w.foot.paused.display = paused

    # What `[window]` says now, so an edit counts in a window that is open. A
    # config that stops reading is said when it does, not on every look.
    async def _read_config(self) -> None:
        after, ignored = await self._outside.history_after()
        notes = [ignored] if ignored and ignored != self._view.read.ignored else []
        self._view.read.ignored = ignored
        if after != self._view.reading.history_after:
            self._view.reading.history_after = after
            moved = clock(after.total_seconds())
            notes.append(f"a cast now moves to history {moved} after it ends")
            self.changed()
        if notes:
            self.say(" · ".join(notes))

    def _paced(self) -> None:
        self._hold()
        self._repaint()

    def _repaint(self) -> None:
        # A tick can land while the app is closing and its widgets are gone.
        mounted = self._w.contents.is_mounted
        if mounted and not self._view.dirty:
            self._w.log.keep_end()
        settled = self._scope.settled(self._casts)
        if not self._view.dirty or not mounted:
            return
        if self._scope.to_fit and not settled:
            return
        self._view.dirty = False
        taken = self._taken()
        listed = self._listed()
        now = datetime.now(UTC)
        where = "all projects" if self._scope.every else named(self._scope.project)
        self._w.foot.scope.update(f"{counted(listed) or 'no casts'}  ({where})")
        reading = self._view.reading
        if self._scope.to_fit and listed and (rows := self._w.contents.size.height):
            self._scope.to_fit = False
            reading.toggled = fitted(casts=listed, reading=reading, now=now, rows=rows)
        old = sum(historic(view, reading, now) for view in listed)
        self._w.foot.hint.update(
            _hint(old, every=self._scope.every) if taken is None else _taken_hint(taken)
        )
        self._paint_contents(listed, now)
        self._paint_ask(listed, self._focused())
        if taken is not None:
            self._w.head.update(taken_head(taken))
            self._w.log.show(
                page=cast_key(taken.hello.cast_id),
                said=taken_output(taken, self._view.claims.mine),
            )
            return
        entry = self._entry()
        self._w.head.update(head(entry, branches=self._view.read.branches, now=now))
        self._w.log.show(page=None if entry is None else entry.key, said=output(entry))

    # Rebuilt only when a line comes or goes, relabelled otherwise, so the
    # cursor stays on the line the operator put it on. When its line goes, the
    # cursor goes to the nearest line above it that is still there; with none,
    # to the first cast, which is what a window opens to look at.
    def _paint_contents(self, listed: list[CastView], now: datetime) -> None:
        drawn, reading = self._view.drawn, self._view.reading
        history = reading.history
        here = self._scope.project if self._scope.every else None
        lines = walked(contents(listed, reading, now))
        entries = {entry.key: entry for entry, _ in lines}
        shape = tuple((entry.key, parent, bool(entry.shown)) for entry, parent in lines)
        if shape == drawn.shape:
            drawn.entries = entries
            for key, node in drawn.nodes.items():
                node.set_label(line_text(entries[key], now, history=history, here=here))
            return
        tree = self._w.contents
        tree.clear()
        nodes: dict[str, TreeNode[str]] = {}
        for entry, parent in lines:
            under = nodes[parent] if parent is not None else tree.root
            text = line_text(entry, now, history=history, here=here)
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

    # One loud line while the cast in view waits on the operator, and a pointer
    # to the next one while some other cast does: a question nobody sees is a
    # cast that never ends. The question itself is in the output of a cast
    # taken over; then what asks elsewhere is one line under the contents.
    def _paint_ask(self, listed: list[CastView], view: CastView | None) -> None:
        taken = self._view.claims.taken is not None
        others = [other for other in listed if other.waiting and other is not view]
        text = ""
        if view is not None and (prompt := top_prompt(view)) is not None and not taken:
            holds = holder(view, prompt, self._view.claims.mine)
            text = f"⏸ {labelled(view.hello)} asks · {holds} · t answers it"
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
