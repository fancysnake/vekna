import asyncio
import contextlib
import math
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from rich.text import Text
from textual.pilot import Pilot
from textual.widgets import Input, Log, Static, Tree
from textual.widgets.tree import TreeNode

from vekna.gates.cli.tui import Opened, ToDaemon, VeknaApp
from vekna.mills.hub import Hub
from vekna.wire import (
    CastCancelRequested,
    CastGoodbye,
    CastHello,
    CastRefused,
    CastRequested,
    CastSeen,
    DecideClaimed,
    DecideReleased,
    DecideRequested,
    DecideResolved,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    TreeBlocked,
    VigilsRequested,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_PAINTED = 0.3
_TICK = 0.01
_PATIENCE = 1000
# The least a Textual tree indents a level by.
_NARROWEST_GUIDES = 2
# A line above the end of a long output, for scrolling up to.
_UP = 10


def _hello(cast_id: str, ritual: str, *, root: str = "/proj") -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root=root,
        project="/proj/.git",
        ritual=ritual,
        components={},
        started_at=_WHEN,
        wired=True,
    )


def _asking_as(hub: Hub, cast_id: str) -> None:
    hub.apply(
        DecideRequested(
            cast_id=cast_id, request_id="q1", prompt="push?", options=["yes", "no"]
        )
    )


# What a cast that began at `_WHEN` says of when.
def _ago() -> str:
    return f"@{(datetime.now(UTC) - _WHEN).days}d ago"


def _asking(hub: Hub) -> None:
    hub.apply(_hello("c1", "pr_fix"))
    hub.apply(
        DecideRequested(
            cast_id="c1", request_id="q1", prompt="push?", options=["yes", "no"]
        )
    )


# The daemon's part in pausing the vigils: it keeps the pause and says it back.
# `said` false is a daemon that does not answer the question.
class _Vigils:
    def __init__(self, *, paused: bool = False, said: bool = True) -> None:
        self.paused = paused
        self.said = said
        self.asked: list[bool | None] = []

    async def __call__(self, asked: VigilsRequested) -> bool | None:
        await asyncio.sleep(0)
        self.asked.append(asked.pause)
        if not self.said:
            return None
        if asked.pause is not None:
            self.paused = asked.pause
        return self.paused


# A window on no casts, over a daemon that keeps `vigils`.
def _vigil_app(vigils: _Vigils) -> VeknaApp:
    async def unasked(_: object) -> None:
        await asyncio.sleep(0)

    return VeknaApp(
        casts=Hub(),
        opened=Opened(project="/proj/.git", root="/proj", history_after=timedelta.max),
        daemon=ToDaemon(send=lambda _: None, mark=unasked, vigils=vigils),
        branch_of=unasked,
    )


# The app over `hub`, keeping what it sends; branches are answered by root.
# Every cast here began at `_WHEN`, long ago, so by default none is history.
def _app(
    hub: Hub,
    sent: list[WireMessage],
    history_after: timedelta = timedelta.max,
    *,
    title: str = "vekna",
    quiet: timedelta = timedelta(seconds=5),
) -> VeknaApp:
    branches = {"/proj": "main", "/trees/1": "fix-ci"}

    # The daemon's part: it keeps the mark and says it back to the window.
    async def mark(request: CastSeen) -> str | None:
        await asyncio.sleep(0)
        reply = hub.mark(request)
        return reply.reason if isinstance(reply, CastRefused) else None

    async def branch_of(root: str) -> str | None:
        await asyncio.sleep(0)
        return branches.get(root)

    return VeknaApp(
        casts=hub,
        opened=Opened(
            project="/proj/.git",
            root="/proj",
            history_after=history_after,
            title=title,
            quiet=quiet,
        ),
        daemon=ToDaemon(send=sent.append, mark=mark, vigils=_Vigils()),
        branch_of=branch_of,
    )


def _text(app: VeknaApp, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


def _nodes(app: VeknaApp) -> list[tuple[int, TreeNode[str]]]:
    tree: Tree[str] = app.query_one("#contents", Tree)
    found: list[tuple[int, TreeNode[str]]] = []

    def walk(node: TreeNode[str], depth: int) -> None:
        for child in node.children:
            found.append((depth, child))
            walk(child, depth + 1)

    walk(tree.root, 0)
    return found


# The contents as read, a line per node, indented by depth. The clock a live
# rite carries moves with the wall, so it is cut where it would be read.
def _contents(app: VeknaApp) -> list[str]:
    return ["  " * depth + str(node.label) for depth, node in _nodes(app)]


def _to(app: VeknaApp, key: str) -> None:
    tree: Tree[str] = app.query_one("#contents", Tree)
    tree.move_cursor(next(node for _, node in _nodes(app) if node.data == key))


def _cursor(app: VeknaApp) -> str | None:
    node = app.query_one("#contents", Tree).cursor_node
    return None if node is None else node.data


def _claim_then(sent: list[WireMessage]) -> DecideClaimed:
    claim = sent[0]
    assert isinstance(claim, DecideClaimed)
    assert claim.claim_id
    return claim


# The output is rewritten on a timer and the follow lands a refresh later; a
# loaded machine takes longer over both than a fixed pause allows.
async def _eventually(pilot: Pilot[None], ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await pilot.pause(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s waiting for the output to catch up"
    raise AssertionError(msg)


def _at_end(log: Log) -> bool:
    return 0 < log.max_scroll_y == log.scroll_y


# A hundred lines of one rite's output, drawn and followed to the end.
@contextlib.asynccontextmanager
async def _long_output() -> AsyncGenerator[tuple[Hub, VeknaApp, Pilot[None], Log]]:
    hub = Hub()
    hub.apply(_hello("c1", "ci_watch"))
    hub.apply(_rite("r1", "watch"))
    for line in range(100):
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
    app = _app(hub, [])
    async with app.run_test() as pilot:
        log = app.query_one("#log", Log)
        await _eventually(pilot, lambda: _at_end(log))
        yield hub, app, pilot, log


# Sixty lines of seventy characters, drawn and followed to the end in a window
# of 120 by 24.
@contextlib.asynccontextmanager
async def _wrapping_output() -> AsyncGenerator[tuple[Hub, VeknaApp, Pilot[None], Log]]:
    hub = Hub()
    hub.apply(_hello("c1", "ci_watch"))
    hub.apply(_rite("r1", "watch"))
    for number in range(60):
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"{number} {'w' * 70}"))
    app = _app(hub, [])
    async with app.run_test(size=(120, 24)) as pilot:
        log = app.query_one("#log", Log)
        await _eventually(pilot, lambda: _at_end(log))
        yield hub, app, pilot, log


def _rite(rite_id: str, name: str, *, parent: str | None = None) -> RiteStarted:
    return RiteStarted(
        cast_id="c1",
        rite_id=rite_id,
        parent_id=parent,
        name=name,
        category="step" if parent is None else "medium",
        started_at=_WHEN,
    )


@pytest.mark.asyncio
class TestContents:
    @staticmethod
    async def test_each_ritual_holds_its_casts_under_their_project():
        hub = Hub()
        hub.apply(_hello("c1abcdef9", "sweep"))
        hub.apply(_hello("c2abcdef9", "ci_watch"))
        hub.apply(_hello("c3abcdef9", "pr_fix"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj (3 running)",
            "  ci_watch",
            "    ▶ @now  c2abcdef",
            "  pr_fix",
            "    ▶ @now  c3abcdef",
            "  sweep",
            "    ▶ @now  c1abcdef",
        ]

    # A sibling of home shares its prefix as a string, not as a path.
    @staticmethod
    @pytest.mark.parametrize(
        ("root", "shown"),
        [("/home/u/x", "~/x"), ("/home/u", "~"), ("/home/u2/x", "/home/u2/x")],
    )
    async def test_a_tree_under_home_is_said_from_home(
        monkeypatch: pytest.MonkeyPatch, root: str, shown: str
    ):
        monkeypatch.setenv("HOME", "/home/u")
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch", root=root))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
        assert head.endswith(f"— · {shown}")

    @staticmethod
    async def test_a_running_cast_reads_as_the_rite_it_is_on():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(_rite("r2", "coding", parent="r1"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r2", delta="[red] check"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            head = _text(app, "#head").splitlines()
            output = "\n".join(app.query_one("#log", Log).lines)
        assert lines[3] == "      …"
        assert lines[4].rsplit("  ", 1)[0] == "      ▶ coding"
        assert [line.rsplit("  ", 1)[0] for line in head[2:]] == [
            "▶ watch",
            "  ▶ coding",
        ]
        assert head[1] == "main · /proj"
        assert output == "[red] check"

    @staticmethod
    async def test_rites_whose_parents_loop_hang_off_the_cast():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch", parent="r2"))
        hub.apply(_rite("r2", "coding", parent="r1"))
        hub.apply(_rite("r3", "shell", parent="r3"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert [line.rsplit("  ", 1)[0] for line in lines[3:]] == [
            "      ▶ watch",
            "        ▶ coding",
            "      ▶ shell",
        ]

    @staticmethod
    async def test_a_cast_that_ended_still_asking_says_so():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        hub.apply(
            DecideRequested(
                cast_id="c1", request_id="q1", prompt="push?", options=["yes", "no"]
            )
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines[:2] == ["proj (1 asks)", "  pr_fix"]
        assert lines[2].endswith("  c1  asks")

    @staticmethod
    async def test_an_ended_cast_stays_as_one_line_beside_the_running_ones():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(_hello("c2", "sweep"))
        hub.apply(CastGoodbye(cast_id="c2", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines[:5] == [
            "proj (1 running)",
            "  nap",
            "    ▶ @now  c1",
            "  finished",
            "    sweep",
        ]
        assert lines[5].startswith("      ✓ @")
        assert lines[5].endswith("  c2")
        assert lines[6:] == []

    @staticmethod
    async def test_a_failed_rite_says_the_first_line_of_why():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(
            RiteFinished(
                cast_id="c1",
                rite_id="r1",
                status="error",
                finished_at=_WHEN,
                error="gh failed\ntraceback",
            )
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines[-1] == "      ✗ watch  0s  gh failed"

    @staticmethod
    async def test_a_long_error_is_cut_in_its_row_and_whole_on_the_page():
        error = "GraphQL: " + "review state is CHANGES_REQUESTED " * 15
        hub = Hub()
        hub.apply(_hello("c1", "merge_ready"))
        hub.apply(_rite("r1", "check_reviews"))
        hub.apply(
            RiteFinished(
                cast_id="c1",
                rite_id="r1",
                status="error",
                finished_at=_WHEN,
                error=error,
            )
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)

            row = _contents(app)[-1]
            page = app.query_one("#head", Static)
            head = str(page.render())
        assert row == "      ✗ check_reviews  0s  GraphQL: review state is CHANGE…"
        assert head.splitlines()[1:] == [error]
        assert page.size.width < len(error)

    @staticmethod
    async def test_a_tree_left_blocked_is_said_under_the_cast():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(TreeBlocked(cast_id="c1", path="/trees/1", reason="dirty"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
        assert head.endswith("\ntree /trees/1 left blocked: dirty")

    @staticmethod
    async def test_why_an_ended_cast_ended_follows_its_output():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "check"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="said"))
        hub.apply(CastGoodbye(cast_id="c1", status="error", detail="boom\ntrace"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "c:c1")
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
        assert output == ["said", " ", "boom", "trace"]

    @staticmethod
    async def test_an_empty_delta_shows_as_a_blank_line():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "check"))
        for delta in ("one", "", "two"):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=delta))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
        assert output == ["one", " ", "two"]

    @staticmethod
    async def test_output_reaches_the_terminal_as_text_only():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "check"))
        for delta in (
            "\x1b[60Cmoved \x1b[31mred\x1b[0m \x1b]8;;http://x\x1b\\link\x1b]8;;\x1b\\",
            "10%\r20%\r",
            "bell\x07 csi\x9b2K",
            "prose " * 100,
        ):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=delta))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)

            log = app.query_one("#log", Log)
            output = list(log.lines)
            drawn = [log.render_line(y) for y in range(len(output))]
            width = log.size.width
        assert output[:4] == ["moved red link", "10%", "20%", "bell� csi�2K"]
        assert "".join(output[4:]) == "prose " * 100
        assert [strip.cell_length for strip in drawn] == [width] * len(output)
        assert [strip.text.isprintable() for strip in drawn] == [True] * len(output)

    @staticmethod
    async def test_the_cursor_stays_on_its_cast_when_another_arrives():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            hub.apply(_hello("c2", "ci_watch"))
            app.changed()
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            head = _text(app, "#head")
            cursor = _cursor(app)
        assert [line.strip() for line in lines[1::2]] == ["ci_watch", "nap"]
        assert cursor == "c:c1"
        assert head.startswith("nap  c1")

    @staticmethod
    async def test_a_cursor_whose_line_goes_moves_to_the_line_it_hung_under():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(_rite("r1", "sleep"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)
            hub.apply(
                RiteFinished(cast_id="c1", rite_id="r1", status="ok", finished_at=_WHEN)
            )
            app.changed()
            await pilot.pause(_PAINTED)

            cursor = _cursor(app)
        assert cursor == "c:c1"

    @staticmethod
    async def test_when_the_last_line_goes_the_cursor_goes_with_it():
        hub = Hub()
        hub.apply(_hello("c1", "nap").model_copy(update={"project": "/other/.git"}))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("g")
            await pilot.pause(_PAINTED)
            await pilot.press("p")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            cursor = _cursor(app)
        assert lines == []
        assert cursor is None

    @staticmethod
    async def test_the_rite_picked_keeps_its_output_when_the_tree_grows():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "first"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one"))
        hub.apply(_rite("r2", "second"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r2", delta="two"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)
            hub.apply(_rite("r3", "third"))
            app.changed()
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
            cursor = _cursor(app)
        assert output == ["one"]
        assert cursor == "t:c1:r1"

    @staticmethod
    async def test_g_shows_every_project_and_p_goes_back_home():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(
            _hello("c2", "ci_watch").model_copy(update={"project": "/other/.git"})
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("g")
            await pilot.pause(_PAINTED)
            every = (_text(app, "#scope"), _contents(app)[::3])
            await pilot.press("p")
            await pilot.pause(_PAINTED)

            home = (_text(app, "#scope"), _contents(app)[::3])
        assert every == (
            "2 running  (all projects)",
            ["other (1 running)", "proj (1 running)"],
        )
        assert home == ("1 running  (proj)", ["proj (1 running)"])


# Two casts that ended two days apart, each with a rite, and one still running.
def _past() -> Hub:
    hub = Hub()
    for cast_id, ritual, days in (("c1", "sweep", 0), ("c2", "nap", 2)):
        hub.apply(_hello(cast_id, ritual))
        hub.apply(_rite("r1", "work").model_copy(update={"cast_id": cast_id}))
        hub.apply(
            RiteFinished(
                cast_id=cast_id,
                rite_id="r1",
                status="ok",
                finished_at=_WHEN + timedelta(days=days, hours=1),
            )
        )
        hub.apply(CastGoodbye(cast_id=cast_id, status="ok"))
    hub.apply(_hello("c3", "ci_watch"))
    return hub


def _day(days: int) -> str:
    return f"{(_WHEN + timedelta(days=days, hours=1)).astimezone():%Y-%m-%d %a}"


def _hour(days: int) -> str:
    return f"{(_WHEN + timedelta(days=days, hours=1)).astimezone():%H:%M}"


@pytest.mark.asyncio
class TestVersion:
    @staticmethod
    async def test_the_version_stands_beside_the_hint():
        app = _app(Hub(), [], title="vekna 1.2.0 · daemon 1.1.0")

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            version = _text(app, "#version")
            hint = _text(app, "#hint")
        assert version == "vekna 1.2.0 · daemon 1.1.0"
        assert hint.endswith("q quit")

    @staticmethod
    async def test_the_hint_stays_whole_in_80_columns():
        app = _app(Hub(), [], title="vekna 3.0.0")

        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(_PAINTED)

            hint_height = app.query_one("#hint", Static).size.height
            foot_height = app.query_one("#foot").size.height
        assert foot_height == hint_height


# A cast of `sweep` that began `age` seconds ago and has ended.
def _ran(hub: Hub, cast_id: str, age: int, **said: object) -> None:
    began = datetime.now(UTC) - timedelta(seconds=age)
    hub.apply(_hello(cast_id, "sweep").model_copy(update={"started_at": began, **said}))
    hub.apply(CastGoodbye(cast_id=cast_id, status="ok", result={"found": []}))


@pytest.mark.asyncio
class TestStreaks:
    @staticmethod
    async def test_casts_that_ended_alike_are_one_line_under_finished():
        hub = Hub()
        hub.apply(_hello("c0", "sweep"))
        hub.apply(CastGoodbye(cast_id="c0", status="error", detail="boom"))
        for cast_id, age in (("c1", 30), ("c2", 20), ("c3", 10)):
            _ran(hub, cast_id, age)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            head = _text(app, "#head").splitlines()
        assert lines == [
            "proj (1 fail)",
            "  finished",
            "    sweep",
            "      ✓ @now  c3  x3",
            f"      ✗ {_ago()}  c0",
        ]
        assert head[-1].startswith("x3 — every cast since ")

    @staticmethod
    async def test_a_line_of_failed_casts_counts_every_failure():
        hub = Hub()
        for cast_id, age in (("c1", 30), ("c2", 20), ("c3", 10)):
            began = datetime.now(UTC) - timedelta(seconds=age)
            hub.apply(_hello(cast_id, "sweep").model_copy(update={"started_at": began}))
            hub.apply(CastGoodbye(cast_id=cast_id, status="error", detail="boom"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj (3 fail)",
            "  finished",
            "    sweep",
            "      ✗ @now  c3  x3",
        ]

    @staticmethod
    async def test_a_line_counts_the_failures_of_every_cast_it_stands_for():
        hub = Hub()
        for parent, kid, age in (("p1", "k1", 30), ("p2", "k2", 20)):
            _ran(hub, parent, age)
            began = datetime.now(UTC) - timedelta(seconds=age - 1)
            hello = _hello(kid, "look").model_copy(
                update={"enqueued_by": parent, "started_at": began}
            )
            hub.apply(hello)
            hub.apply(CastGoodbye(cast_id=kid, status="error", detail="boom"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines[0] == "proj (2 fail)"

    @staticmethod
    async def test_the_finished_line_lists_its_casts_on_the_right_page():
        hub = Hub()
        for cast_id, age in (("c1", 30), ("c2", 20)):
            _ran(hub, cast_id, age)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "f:p:/proj/.git")
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
        assert head.splitlines()[0] == "finished"
        assert "c1" in head
        assert "c2" in head
        assert "/proj" not in head

    @staticmethod
    async def test_a_ritual_line_lists_the_casts_queued_under_its_casts():
        hub = Hub()
        hub.apply(_hello("c1", "sweep"))
        hub.apply(_hello("k1", "look").model_copy(update={"enqueued_by": "c1"}))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "r:/proj/.git:sweep")
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
        assert "c1" in head
        assert "k1" in head

    @staticmethod
    async def test_a_line_stands_for_the_casts_of_one_slot_only():
        hub = Hub()
        minutes = {"c1": 150, "c2": 120, "c3": 30}
        for cast_id, age in minutes.items():
            _ran(hub, cast_id, age * 60)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj",
            "  finished",
            "    sweep",
            "      ✓ @<1h  c3",
            "      ✓ @<3h  c2  x2",
        ]

    @staticmethod
    async def test_casts_of_one_slot_that_did_not_fail_are_one_line():
        hub = Hub()
        began = datetime.now(UTC) - timedelta(hours=4)
        for cast_id, found in (("c1", ["a"]), ("c2", [])):
            began += timedelta(minutes=1)
            hello = _hello(cast_id, "sweep").model_copy(update={"started_at": began})
            hub.apply(hello)
            hub.apply(CastGoodbye(cast_id=cast_id, status="ok", result=found))
        hub.apply(_hello("k1", "look").model_copy(update={"enqueued_by": "c2"}))
        hub.apply(CastGoodbye(cast_id="k1", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj",
            "  finished",
            "    sweep",
            "      ✓ @<6h  c2  x2",
            "        ✓ look  k1",
        ]

    @staticmethod
    async def test_a_cast_still_running_is_never_folded_into_the_one_before():
        hub = Hub()
        _ran(hub, "c1", 20)
        hub.apply(_hello("c2", "sweep"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj (1 running)",
            "  sweep",
            "    ▶ @now  c2",
            "  finished",
            "    sweep",
            "      ✓ @now  c1",
        ]

    @staticmethod
    async def test_casts_of_other_arguments_do_not_fold_and_say_no_argument():
        hub = Hub()
        _ran(hub, "c1", 20, components={"number": 1, "batch": 7})
        _ran(hub, "c2", 10, components={"number": 2, "batch": 7})
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj",
            "  finished",
            "    sweep",
            "      ✓ @now  c2",
            "      ✓ @now  c1",
        ]

    @staticmethod
    async def test_f_folds_every_line_and_f_again_opens_them_all():
        hub = Hub()
        _ran(hub, "c1", 20)
        hub.apply(_hello("c2", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            tree = _contents(app)
            await pilot.press("f")
            await pilot.pause(_PAINTED)
            folded = _contents(app)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            inside = _contents(app)
            await pilot.press("f")
            await pilot.pause(_PAINTED)
            await pilot.press("f")
            await pilot.pause(_PAINTED)

            back = _contents(app)
        assert folded == ["▸ proj (1 running)"]
        assert inside == ["proj (1 running)", "  ▸ nap (1 running)", "  ▸ finished"]
        assert back == tree

    @staticmethod
    async def test_a_cast_whose_queued_cast_still_runs_is_not_folded():
        hub = Hub()
        _ran(hub, "c1", 30)
        _ran(hub, "c2", 20)
        hub.apply(_hello("c3", "pr_fix").model_copy(update={"enqueued_by": "c2"}))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj (1 running)",
            "  sweep",
            "    ✓ @now  c2",
            "      ▶ pr_fix  c3",
            "  finished",
            "    sweep",
            "      ✓ @now  c1",
        ]

    @staticmethod
    async def test_casts_fold_when_what_they_queued_ended_alike_too():
        hub = Hub()
        for parent, kid, age in (("c1", "k1", 30), ("c2", "k2", 20)):
            _ran(hub, parent, age)
            hub.apply(_hello(kid, "pr_fix").model_copy(update={"enqueued_by": parent}))
            hub.apply(CastGoodbye(cast_id=kid, status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj",
            "  finished",
            "    sweep",
            "      ✓ @now  c2  x2",
            "        ✓ pr_fix  k2",
        ]

    @staticmethod
    async def test_casts_whose_queued_casts_moved_to_history_still_fold_by_them():
        hub = Hub()
        long_ago = datetime.now(UTC) - timedelta(hours=2)
        for parent, kid, age, status in (
            ("c1", "k1", 30, "ok"),
            ("c2", "k2", 20, "error"),
        ):
            _ran(hub, parent, age)
            hub.apply(
                _hello(kid, "pr_fix").model_copy(
                    update={"enqueued_by": parent, "started_at": long_ago}
                )
            )
            hub.apply(CastGoodbye(cast_id=kid, status=status))
        app = _app(hub, [], history_after=timedelta(hours=1))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == [
            "proj",
            "  finished",
            "    sweep",
            "      ✓ @now  c2",
            "      ✓ @now  c1",
        ]

    @staticmethod
    async def test_a_cast_that_ended_folds_its_rites_and_still_shows_its_queued():
        hub = Hub()
        hub.apply(_hello("c1", "sweep"))
        hub.apply(_rite("r1", "look"))
        hub.apply(
            RiteFinished(cast_id="c1", rite_id="r1", status="ok", finished_at=_WHEN)
        )
        hub.apply(_hello("k1", "pr_fix").model_copy(update={"enqueued_by": "c1"}))
        hub.apply(CastGoodbye(cast_id="k1", status="ok"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            folded = _contents(app)
            _to(app, "c:c1")
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            opened = _contents(app)
        assert folded == [
            "proj",
            "  finished",
            "    sweep",
            f"      ▸ ✓ {_ago()}  c1",
            "        ✓ pr_fix  k1",
        ]
        assert opened == [
            "proj",
            "  finished",
            "    sweep",
            f"      ✓ {_ago()}  c1",
            "        ✓ look  0s",
            "        ✓ pr_fix  k1",
        ]

    @staticmethod
    async def test_queued_casts_of_one_ritual_say_their_ritual_and_no_argument():
        hub = Hub()
        hub.apply(_hello("c1", "sweep"))
        for kid, number in (("k1", 1), ("k2", 2)):
            hub.apply(
                _hello(kid, "pr_fix").model_copy(
                    update={"enqueued_by": "c1", "components": {"number": number}}
                )
            )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines[-2:] == ["      ▶ pr_fix  k1", "      ▶ pr_fix  k2"]

    @staticmethod
    async def test_a_queued_cast_hangs_under_the_cast_that_queued_it():
        hub = Hub()
        hub.apply(_hello("c1", "sweep"))
        hub.apply(_hello("c2", "pr_fix").model_copy(update={"enqueued_by": "c1"}))
        _asking_as(hub, "c2")
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            lines = _contents(app)
            await pilot.press("w")
            await pilot.pause(_PAINTED)

            cursor = _cursor(app)
        assert lines == [
            "proj (1 asks, 1 running)",
            "  sweep",
            "    ▶ @now  c1",
            "      ⏸ pr_fix  c2  asks",
        ]
        assert cursor == "c:c2"


# Longer than a fitting window waits for its casts to stop arriving.
_SETTLED = 0.8


def _running(hub: Hub) -> None:
    hub.apply(_hello("c1", "ci_watch"))
    hub.apply(_rite("r1", "watch"))
    hub.apply(RiteFinished(cast_id="c1", rite_id="r1", status="ok", finished_at=_WHEN))
    hub.apply(_rite("r2", "report"))


def _ended(hub: Hub) -> None:
    hub.apply(_hello("c2", "sweep"))
    hub.apply(CastGoodbye(cast_id="c2", status="ok"))


# A window that fits its tree to its height, over a project with a cast two
# rites in and a cast that ended.
def _fitting(hub: Hub | None = None) -> VeknaApp:
    if hub is None:
        hub = Hub()
        _running(hub)
        _ended(hub)

    async def branch_of(_: str) -> str | None:
        await asyncio.sleep(0)
        return "main"

    async def mark(_: CastSeen) -> str | None:
        await asyncio.sleep(0)
        return None

    return VeknaApp(
        casts=hub,
        opened=Opened(
            project="/proj/.git", root="/proj", history_after=timedelta.max, fit=True
        ),
        daemon=ToDaemon(send=lambda _: None, mark=mark, vigils=_Vigils()),
        branch_of=branch_of,
    )


# The contents without what moves with the clock: each line to its first word
# after the glyph.
def _shape(app: VeknaApp) -> list[str]:
    return [line.strip().split("  ")[0] for line in _contents(app)]


@pytest.mark.asyncio
class TestFitting:
    @staticmethod
    async def test_a_tall_window_opens_with_the_running_cast_whole():
        app = _fitting()

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(_SETTLED)

            lines = _shape(app)
        assert lines == [
            "proj (1 running)",
            "ci_watch",
            "▶ @now",
            "✓ watch",
            "▶ report",
            "finished",
            "sweep",
            f"✓ {_ago()}",
        ]

    @staticmethod
    async def test_a_short_window_opens_with_all_but_what_runs_folded():
        app = _fitting()

        async with app.run_test(size=(100, 9)) as pilot:
            await pilot.pause(_SETTLED)

            lines = _shape(app)
        assert lines == [
            "proj (1 running)",
            "ci_watch",
            "▶ @now",
            "✓ watch",
            "▶ report",
            "▸ finished",
        ]

    @staticmethod
    async def test_the_tree_is_fitted_to_every_cast_the_daemon_replays(
        monkeypatch: pytest.MonkeyPatch,
    ):
        # The replay lasts as long as the test says, however slow the machine.
        monkeypatch.setattr("vekna.gates.cli.tui._SETTLE_SECONDS", math.inf)
        monkeypatch.setattr("vekna.gates.cli.tui._FIT_WAIT_SECONDS", math.inf)
        hub = Hub()
        _running(hub)
        app = _fitting(hub)

        async with app.run_test(size=(100, 9)) as pilot:
            await pilot.pause(_PAINTED)
            early = _shape(app)
            _ended(hub)
            app.changed()
            monkeypatch.setattr("vekna.gates.cli.tui._SETTLE_SECONDS", 0)
            await _eventually(pilot, lambda: bool(_shape(app)))

            lines = _shape(app)
        assert early == []
        assert lines == [
            "proj (1 running)",
            "ci_watch",
            "▶ @now",
            "✓ watch",
            "▶ report",
            "▸ finished",
        ]

    @staticmethod
    @pytest.mark.parametrize("key", ["g", "p"])
    async def test_a_change_of_scope_fits_the_tree_again(key: str):
        app = _fitting()

        async with app.run_test(size=(100, 9)) as pilot:
            await pilot.pause(_SETTLED)
            await pilot.press("f")
            await pilot.pause(_PAINTED)
            folded = _shape(app)
            await pilot.press(key)
            await pilot.pause(_PAINTED)

            lines = _shape(app)
        assert folded == ["▸ proj (1 running)"]
        assert lines == [
            "proj (1 running)",
            "ci_watch",
            "▶ @now",
            "✓ watch",
            "▶ report",
            "▸ finished",
        ]

    @staticmethod
    async def test_the_every_project_command_fits_the_tree_again():
        app = _fitting()

        async with app.run_test(size=(100, 9)) as pilot:
            await pilot.pause(_SETTLED)
            await pilot.press("f", ":", "g", "enter")
            await pilot.pause(_PAINTED)

            lines = _shape(app)
        assert lines == [
            "proj (1 running)",
            "ci_watch",
            "▶ @now",
            "✓ watch",
            "▶ report",
            "▸ finished",
        ]

    @staticmethod
    async def test_a_daemon_that_never_goes_quiet_does_not_hold_the_tree_back(
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr("vekna.gates.cli.tui._FIT_WAIT_SECONDS", 0.5)
        hub = Hub()
        _running(hub)
        app = _fitting(hub)

        async with app.run_test(size=(100, 9)) as pilot:
            for number in range(8):
                hub.apply(_hello(f"n{number}", "sweep"))
                app.changed()
                await pilot.pause(_PAINTED / 3)

            lines = _shape(app)
        assert lines


@pytest.mark.asyncio
class TestWidth:
    @staticmethod
    async def test_a_line_wider_than_the_contents_is_cut_not_scrolled():
        hub = Hub()
        hub.apply(_hello("c1", "a_ritual_with_a_name_wider_than_the_contents_page"))
        app = _app(hub, [])

        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("k", "j", "j", "right", "end")
            await pilot.pause(_PAINTED)

            tree = app.query_one("#contents", Tree)
        assert not tree.show_horizontal_scrollbar
        assert tree.scroll_x == 0
        assert tree.guide_depth == _NARROWEST_GUIDES


@pytest.mark.asyncio
class TestHistory:
    @staticmethod
    async def test_the_hint_counts_the_casts_the_history_view_has():
        app = _app(_past(), [], history_after=timedelta(0))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            hint = _text(app, "#hint")
        assert lines == ["proj (1 running)", "  ci_watch", "    ▶ @now  c3"]
        assert "H history (2)" in hint

    @staticmethod
    async def test_h_shows_the_ended_casts_by_day_newest_first_and_goes_back():
        app = _app(_past(), [], history_after=timedelta(0))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            tree = _contents(app)
            await pilot.press("H")
            await pilot.pause(_PAINTED)
            history = _contents(app)
            note = _text(app, "#note")
            await pilot.press("H")
            await pilot.pause(_PAINTED)

            back = _contents(app)
        assert history == [
            _day(2),
            f"  ▸ ✓ {_hour(2)}  nap  c2",
            _day(0),
            f"  ▸ ✓ {_hour(0)}  sweep  c1",
        ]
        assert note == "history view"
        assert back == tree

    @staticmethod
    async def test_h_stays_in_the_tree_view_while_no_cast_is_old_enough():
        app = _app(_past(), [], history_after=timedelta(hours=1000000))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            tree = _contents(app)
            await pilot.press("g")
            await pilot.press("H")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
            note = _text(app, "#note")
        assert lines == tree
        assert note == "no history yet — a cast moves there 1000000h00m after it ends"

    @staticmethod
    async def test_a_history_cast_opens_and_its_day_folds_and_lists_its_casts():
        app = _app(_past(), [], history_after=timedelta(0))

        async with app.run_test() as pilot:
            await pilot.press("H")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            opened = _contents(app)
            _to(app, f"d:{_day(2)}")
            await pilot.pause(_PAINTED)
            head = _text(app, "#head").splitlines()
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            folded = _contents(app)
        assert opened[:3] == [_day(2), f"  ✓ {_hour(2)}  nap  c2", "    ✓ work  49h00m"]
        assert head[0] == _day(2)
        assert head[1].startswith(f"✓ {_hour(2)}  nap  c2")
        assert folded[0] == f"▸ {_day(2)}"

    @staticmethod
    async def test_a_cast_that_ended_within_the_setting_stays_in_the_tree_view():
        hub = Hub()
        hub.apply(
            _hello("c1", "sweep").model_copy(update={"started_at": datetime.now(UTC)})
        )
        hub.apply(CastGoodbye(cast_id="c1", status="error"))
        app = _app(hub, [], history_after=timedelta(days=1))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == ["proj (1 fail)", "  finished", "    sweep", "      ✗ @now  c1"]


@pytest.mark.asyncio
class TestFolding:
    @staticmethod
    async def test_a_fold_hides_its_lines_and_says_what_still_happens_there():
        hub = Hub()
        _asking(hub)
        hub.apply(_hello("c2", "ci_watch"))
        hub.apply(_hello("c3", "ci_watch"))
        hub.apply(CastGoodbye(cast_id="c3", status="error"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            before = _contents(app)
            _to(app, "p:/proj/.git")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            folded = _contents(app)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            unfolded = _contents(app)
        assert folded == ["▸ proj (1 asks, 1 fail, 1 running)"]
        assert unfolded == before
        assert len(before) > 1

    @staticmethod
    async def test_a_cast_watched_as_it_fails_stays_when_the_cursor_leaves():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)
            hub.apply(
                RiteFinished(
                    cast_id="c1",
                    rite_id="r1",
                    status="error",
                    error="boom",
                    finished_at=_WHEN,
                )
            )
            hub.apply(CastGoodbye(cast_id="c1", status="error"))
            app.changed()
            await pilot.pause(_PAINTED)
            _to(app, "p:/proj/.git")
            await pilot.pause(_PAINTED)

            left = _contents(app)
        assert left[:3] == ["proj (1 fail)", "  finished", "    ci_watch"]
        assert left[3].endswith("  c1")

    @staticmethod
    async def test_space_on_a_cast_opens_its_whole_rite_tree_and_closes_it_again():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(
            RiteFinished(cast_id="c1", rite_id="r1", status="ok", finished_at=_WHEN)
        )
        hub.apply(_rite("r2", "repair"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "…:c1")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            brief = _contents(app)
            _to(app, "c:c1")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            whole = _contents(app)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            again = _contents(app)
        assert [line.strip().split("  ")[0] for line in brief[3:]] == ["…", "▶ repair"]
        assert [line.strip().split("  ")[0] for line in whole[3:]] == [
            "✓ watch",
            "▶ repair",
        ]
        assert [line.strip().split("  ")[0] for line in again[3:]] == ["…", "▶ repair"]

    @staticmethod
    async def test_a_rite_folds_over_the_rites_under_it():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(_rite("r2", "coding", parent="r1"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            folded = _contents(app)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            unfolded = _contents(app)
        assert [line.strip().split("  ")[0] for line in folded[3:]] == ["▸ ▶ watch"]
        assert [line.strip().split("  ")[0] for line in unfolded[3:]] == [
            "▶ watch",
            "▶ coding",
        ]

    @staticmethod
    async def test_space_on_a_failed_cast_opens_its_rites():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(
            RiteFinished(
                cast_id="c1",
                rite_id="r1",
                status="error",
                error="boom",
                finished_at=_WHEN,
            )
        )
        hub.apply(CastGoodbye(cast_id="c1", status="error"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert [line.strip().split("  ")[0] for line in lines[4:]] == ["✗ watch"]

    @staticmethod
    async def test_a_line_with_nothing_under_it_does_not_fold():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert lines == ["proj (1 running)", "  nap", "    ▶ @now  c1"]

    @staticmethod
    async def test_t_answers_a_question_folded_away():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "r:/proj/.git:pr_fix")
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            folded = _contents(app)
            await pilot.press("w", "t")
            await pilot.pause(_PAINTED)

            claim = _claim_then(sent)
        assert folded == ["proj (1 asks)", "  ▸ pr_fix (1 asks)"]
        assert claim.request_id == "q1"


@pytest.mark.asyncio
class TestWaiting:
    @staticmethod
    async def test_the_question_is_a_banner_and_marks_the_rite_that_asked():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(_rite("r1", "fix"))
        hub.apply(
            DecideRequested(
                cast_id="c1",
                rite_id="r1",
                request_id="q1",
                prompt="push?",
                options=["yes", "no"],
            )
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            ask = _text(app, "#ask")
            lines = _contents(app)
        assert ask == "⏸ pr_fix c1 asks · open · t answers it"
        assert lines[2] == "    ⏸ @now  c1  asks"
        assert lines[3].startswith("      ▶ fix  ")
        assert lines[3].endswith("  asks")

    @staticmethod
    async def test_w_moves_to_the_cast_waiting_on_the_operator():
        hub = Hub()
        hub.apply(_hello("c2", "ci_watch"))
        _asking(hub)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            pointer = _text(app, "#ask")
            await pilot.press("w")
            await pilot.pause(_PAINTED)

            ask = _text(app, "#ask")
        assert pointer == "⏸ 1 cast waits on you · w goes to it"
        assert ask.startswith("⏸ pr_fix ")

    @staticmethod
    async def test_w_in_the_history_view_returns_to_the_tree_and_the_waiting_cast():
        hub = _past()
        hub.apply(_hello("c4", "pr_fix"))
        hub.apply(DecideRequested(cast_id="c4", request_id="q4", prompt="push?"))
        app = _app(hub, [], history_after=timedelta(0))

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("H")
            await pilot.pause(_PAINTED)
            history = _contents(app)
            await pilot.press("w")
            await pilot.pause(_PAINTED)
            await _eventually(pilot, lambda: _cursor(app) == "c:c4")

            note = _text(app, "#note")
            ask = _text(app, "#ask")
        assert history == [
            _day(2),
            f"  ▸ ✓ {_hour(2)}  nap  c2",
            _day(0),
            f"  ▸ ✓ {_hour(0)}  sweep  c1",
        ]
        assert note == "tree view"
        assert ask.startswith("⏸ pr_fix ")

    @staticmethod
    async def test_with_no_cast_waiting_w_says_so():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("w")

            note = _text(app, "#note")
        assert note == "no cast is waiting on you"

    @staticmethod
    async def test_a_prompt_claimed_by_another_window_says_so():
        hub = Hub()
        _asking(hub)
        hub.apply(DecideClaimed(cast_id="c1", request_id="q1", claim_id="other"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            ask = _text(app, "#ask")
        assert ask == "⏸ pr_fix c1 asks · claimed elsewhere · t answers it"


@pytest.mark.asyncio
class TestCommands:
    @staticmethod
    async def test_c_asks_the_daemon_for_a_cast_here():
        sent: list[WireMessage] = []
        app = _app(Hub(), sent)

        async with app.run_test() as pilot:
            await pilot.press("c", *"sweep --max-prs 1", "enter")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
        assert sent == [
            CastRequested(
                project_root="/proj", ritual="sweep", components={"max_prs": "1"}
            )
        ]
        assert note == "asked for sweep"

    @staticmethod
    async def test_a_line_that_means_nothing_says_what_does():
        app = _app(Hub(), [])

        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.press("ctrl+u", *"zap", "enter")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
        assert note.startswith("'zap' means nothing here")

    @staticmethod
    async def test_an_empty_line_says_nothing():
        sent: list[WireMessage] = []
        app = _app(Hub(), sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            before = _text(app, "#note")
            await pilot.press("c", "ctrl+u", "enter")
            await pilot.pause()

            note = _text(app, "#note")
            running = app.is_running
        assert note == before
        assert running
        assert not sent

    @staticmethod
    async def test_q_typed_quits():
        app = _app(Hub(), [])

        async with app.run_test() as pilot:
            await pilot.press("c", "ctrl+u", "q", "enter")
            await pilot.pause()

            running = app.is_running
        assert not running

    @staticmethod
    async def test_g_typed_shows_every_project():
        app = _app(Hub(), [])

        async with app.run_test() as pilot:
            await pilot.press("c", "ctrl+u", "g", "enter")
            await pilot.pause(_PAINTED)

            title = _text(app, "#scope")
        assert title == "no casts  (all projects)"

    @staticmethod
    async def test_an_empty_window_says_which_projects_it_shows():
        app = _app(Hub(), [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            home = _text(app, "#scope")
            await pilot.press("g")
            await pilot.pause(_PAINTED)

            every = _text(app, "#scope")
        assert home == "no casts  (proj)"
        assert every == "no casts  (all projects)"

    @staticmethod
    async def test_t_typed_takes_the_prompt_over():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("c", "ctrl+u", "t", "enter")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
        assert note == "took over pr_fix c1"
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_an_answer_with_nothing_waiting_says_so():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("a", *"yes", "enter")
            await pilot.pause()

            note = _text(app, "#note")
        assert not sent
        assert note == "nothing to answer — pick a waiting cast first"


# `t` on the asking cast, painted, so its first prompt is claimed.
async def _take(pilot: Pilot[None]) -> None:
    await pilot.pause(_PAINTED)
    await pilot.press("t")
    await pilot.pause(_PAINTED)


@pytest.mark.asyncio
class TestTakingOver:
    @staticmethod
    async def test_t_claims_the_prompt_and_enter_answers_it():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            banner = app.query_one("#ask", Static).display
            asked = list(app.query_one("#log", Log).lines)
            line = app.query_one("#answer", Input)
            typing = line.display and line.has_focus
            await pilot.press(*"no", "enter")
            await pilot.pause()

            note = _text(app, "#note")
        claim = _claim_then(sent)
        assert not banner
        assert asked == ["? push?", "    yes | no"]
        assert typing
        assert note == "answered no"
        assert sent == [
            DecideClaimed(cast_id="c1", request_id="q1", claim_id=claim.claim_id),
            DecideResolved(cast_id="c1", request_id="q1", answer="no"),
        ]

    @staticmethod
    async def test_every_later_prompt_is_claimed_without_another_t():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            await pilot.press(*"yes", "enter")
            for answered, asked in (("q1", "q2"), ("q2", "q3")):
                hub.apply(
                    DecideResolved(cast_id="c1", request_id=answered, answer="yes")
                )
                hub.apply(
                    DecideRequested(
                        cast_id="c1", request_id=asked, prompt="again?", free=True
                    )
                )
                app.changed()
                await pilot.pause(_PAINTED)
                await pilot.press(*asked, "enter")
            await pilot.pause()

        kinds = [(message.kind, getattr(message, "request_id", "")) for message in sent]
        assert kinds == [
            ("decide_claimed", "q1"),
            ("decide_resolved", "q1"),
            ("decide_claimed", "q2"),
            ("decide_resolved", "q2"),
            ("decide_claimed", "q3"),
            ("decide_resolved", "q3"),
        ]

    @staticmethod
    async def test_a_free_prompt_takes_what_is_typed():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(
            DecideRequested(cast_id="c1", request_id="q1", prompt="why?", free=True)
        )
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            await pilot.press(*"flaky", "enter")
            await pilot.pause()

        claim = _claim_then(sent)
        assert sent == [
            claim,
            DecideResolved(cast_id="c1", request_id="q1", answer="flaky"),
        ]

    @staticmethod
    async def test_an_answer_not_offered_is_refused_and_the_takeover_stays():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            await pilot.press(*"maybe", "enter")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
            hint = _text(app, "#hint")
        assert note == "'maybe' is not one of yes, no"
        assert hint == (
            "taken over pr_fix c1 · enter answers"
            " · esc leaves and hands the prompts back"
        )
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_escape_hands_the_prompt_back_and_the_contents_take_keys_again():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            locked = app.query_one("#contents", Tree).disabled
            await pilot.press("escape")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
            tree = app.query_one("#contents", Tree)
            usable = tree.has_focus and not tree.disabled
            line = app.query_one("#answer", Input).display
        claim = _claim_then(sent)
        assert locked
        assert sent == [claim, DecideReleased(cast_id="c1", request_id="q1")]
        assert note == "left pr_fix c1 — its prompts are handed back"
        assert usable
        assert not line

    @staticmethod
    async def test_a_running_cast_is_taken_over_before_it_asks():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            head = _text(app, "#head")
            await pilot.press("enter")
            await pilot.pause()
            note = _text(app, "#note")
            quiet = list(sent)
            hub.apply(
                DecideRequested(cast_id="c1", request_id="q1", prompt="go?", free=True)
            )
            app.changed()
            await pilot.pause(_PAINTED)

        assert head == " ◆ taken over · ci_watch c1  esc leaves\nno output yet"
        assert note == "the cast asks nothing right now"
        assert not quiet
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_the_left_page_opens_the_rites_of_a_cast_taken_from_under_a_fold():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(_rite("r1", "fetch"))
        hub.apply(_rite("r2", "fix"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r2", delta="editing"))
        hub.apply(
            DecideRequested(
                cast_id="c1", rite_id="r2", request_id="q1", prompt="push?\nnow?"
            )
        )
        hub.apply(DecideClaimed(cast_id="c1", request_id="q1", claim_id="other"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "p:/proj/.git")
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            folded = len(_contents(app))
            await _take(pilot)

            rites = [str(node.label).split()[1] for _, node in _nodes(app)[3:]]
            head = _text(app, "#head")
            said = list(app.query_one("#log", Log).lines)
            await pilot.press("escape")
            await pilot.pause(_PAINTED)
            left = len(_contents(app))
        assert folded == 1
        assert rites == ["fetch", "fix"]
        assert head == " ◆ taken over · pr_fix c1  esc leaves\nfix · live"
        assert said == [
            "editing",
            "? push?",
            "  now?",
            "    yes | no · claimed elsewhere",
        ]
        assert left == 1

    @staticmethod
    async def test_the_takeover_ends_once_the_cast_asks_nothing_after_an_answer():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent, quiet=timedelta(seconds=1))

        async with app.run_test() as pilot:
            tree: Tree[str] = app.query_one("#contents", Tree)
            await _take(pilot)
            await pilot.press(*"no", "enter")
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="no"))
            app.changed()
            await pilot.pause(_PAINTED)
            held = tree.disabled
            await _eventually(pilot, lambda: not tree.disabled)

            note = _text(app, "#note")
        assert held
        assert note == "left pr_fix c1 — it asks nothing more"
        assert sent == [
            _claim_then(sent),
            DecideResolved(cast_id="c1", request_id="q1", answer="no"),
        ]

    @staticmethod
    async def test_the_takeover_ends_with_its_cast():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
            hub.apply(CastGoodbye(cast_id="c1", status="ok"))
            app.changed()
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
            locked = app.query_one("#contents", Tree).disabled
        assert note == "the cast taken over has ended"
        assert not locked
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_a_prompt_from_another_cast_is_one_line_under_the_contents():
        hub = Hub()
        _asking(hub)
        hub.apply(_hello("c2", "nap"))
        hub.apply(DecideRequested(cast_id="c2", request_id="q2", prompt="wake?"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "c:c1")
            await _take(pilot)
            one = _text(app, "#elsewhere")
            hub.apply(_hello("c3", "sweep"))
            hub.apply(DecideRequested(cast_id="c3", request_id="q3", prompt="all?"))
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
            app.changed()
            await pilot.pause(_PAINTED)
            many = _text(app, "#elsewhere")
            top = app.query_one("#ask", Static).display
            await pilot.press("escape")
            await pilot.pause(_PAINTED)

            under = app.query_one("#elsewhere", Static).display
        assert one == "? nap c2 asks too"
        assert many == "? 2 other casts ask too"
        assert not top
        assert not under

    # With the output in focus the window's keys work again: none of them
    # starts a second takeover or puts a command on the answer line.
    @staticmethod
    async def test_t_and_c_change_nothing_while_a_cast_is_taken_over():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            app.query_one("#log", Log).focus()
            await pilot.press("t", "c")
            await pilot.pause(_PAINTED)

            typed = app.query_one("#answer", Input).value
        assert not typed
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_the_contents_keys_do_nothing_while_a_cast_is_taken_over():
        hub = Hub()
        _asking(hub)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await _take(pilot)
            app.query_one("#log", Log).focus()
            await pilot.press("w", "H", "g", "p")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
            where = _text(app, "#scope")
        assert note == "took over pr_fix c1"
        assert where == "1 waiting  (proj)"

    @staticmethod
    async def test_an_empty_line_is_not_sent_as_an_answer():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(
            DecideRequested(cast_id="c1", request_id="q1", prompt="why?", free=True)
        )
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            await pilot.press("enter")
            await pilot.pause()

            note = _text(app, "#note")
        assert note == "type an answer first"
        assert sent == [_claim_then(sent)]

    @staticmethod
    async def test_a_draft_typed_for_one_question_is_not_sent_to_the_next():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(
            DecideRequested(cast_id="c1", request_id="q1", prompt="why?", free=True)
        )
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await _take(pilot)
            await pilot.press(*"flak")
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="other"))
            hub.apply(
                DecideRequested(
                    cast_id="c1", request_id="q2", prompt="when?", free=True
                )
            )
            app.changed()
            await pilot.pause(_PAINTED)
            await pilot.press("y", "enter")
            await pilot.pause()

            note = _text(app, "#note")
            typed = app.query_one("#answer", Input).value
        assert note == "the question changed — your answer was not sent"
        assert not typed
        assert [message.kind for message in sent] == ["decide_claimed"] * 2

    @staticmethod
    async def test_a_answers_without_a_claim_and_refuses_what_is_not_offered():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("a", *"maybe", "enter")
            await pilot.pause()
            refused = _text(app, "#note")
            await pilot.press("a", *"yes", "enter")
            await pilot.pause()

        assert refused == "'maybe' is not one of yes, no"
        assert sent == [DecideResolved(cast_id="c1", request_id="q1", answer="yes")]

    @staticmethod
    async def test_a_cast_that_ended_is_not_taken_over():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()

            note = _text(app, "#note")
        assert not sent
        assert note == "only a running cast can be taken over"


@pytest.mark.asyncio
class TestCancelling:
    @staticmethod
    async def test_the_second_x_cancels_the_cast_the_first_one_named():
        hub = Hub()
        hub.apply(_hello("c1abcdef9", "nap"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("x")
            armed = _text(app, "#note")
            held = list(sent)
            await pilot.press("x")
            await pilot.pause()

            note = _text(app, "#note")
        assert armed == "x again cancels nap c1abcdef"
        assert not held
        assert sent == [CastCancelRequested(cast_id="c1abcdef9")]
        assert note == "asked nap c1abcdef to stop"

    @staticmethod
    async def test_a_cast_that_ended_is_not_cancelled():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("x", "x")
            await pilot.pause()

            note = _text(app, "#note")
        assert not sent
        assert note == "only a running cast can be cancelled"


@pytest.mark.asyncio
class TestFollowing:
    @staticmethod
    async def test_the_output_ends_on_the_newest_line_as_more_arrives():
        async with _long_output() as (hub, app, pilot, log):
            first = (log.scroll_y, log.max_scroll_y)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="newest"))
            app.changed()
            await _eventually(
                pilot, lambda: log.max_scroll_y > first[1] and _at_end(log)
            )

            then = (log.scroll_y, log.max_scroll_y)
        assert first[1] > 0
        assert first[0] == first[1]
        assert then[0] == then[1]

    @staticmethod
    async def test_the_output_ends_on_the_newest_line_when_the_window_shrinks():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        for line in range(100):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            before = log.max_scroll_y
            await pilot.resize_terminal(80, 16)
            await pilot.pause(_PAINTED)

            after = (log.scroll_y, log.max_scroll_y)
        assert after[1] > before
        assert after[0] == after[1]

    @staticmethod
    async def test_scrolling_up_stops_the_follow_and_the_end_starts_it_again():
        async with _long_output() as (hub, app, pilot, log):
            left = log.max_scroll_y
            log.scroll_to(y=_UP, animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one more"))
            app.changed()
            await _eventually(pilot, lambda: log.max_scroll_y > left)
            await pilot.pause(_PAINTED)
            held = log.scroll_y
            log.scroll_end(animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="and another"))
            app.changed()
            await _eventually(
                pilot, lambda: log.max_scroll_y > left + 1 and _at_end(log)
            )

            again = (log.scroll_y, log.max_scroll_y)
        assert held == _UP
        assert again[0] == again[1]

    # The follow lands a refresh after the repaint that asked for it; the
    # operator's scroll in between is the newer word. The scroll is made as the
    # follow is asked for, so it always lands in between. Only the follow
    # passes where it asked from; Textual's own scroll to the end asks for a
    # refresh too, and passes nothing.
    @staticmethod
    async def test_scrolling_up_before_the_follow_lands_stops_it(
        monkeypatch: pytest.MonkeyPatch,
    ):
        async with _long_output() as (hub, app, pilot, log):
            drawn = log.line_count
            after_refresh = log.call_after_refresh

            def scrolled_first(callback: Callable[..., object], *args: float) -> bool:
                if args:
                    monkeypatch.undo()
                    log.scroll_to(y=_UP, animate=False, immediate=True)
                return after_refresh(callback, *args)

            monkeypatch.setattr(log, "call_after_refresh", scrolled_first)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one more"))
            app.changed()
            await _eventually(pilot, lambda: log.line_count != drawn)
            await pilot.pause(_PAINTED)

            held = log.scroll_y
        assert held == _UP

    # Past where the follow last left the end, but short of the new one.
    @staticmethod
    async def test_scrolling_down_short_of_the_end_keeps_the_follow_stopped():
        async with _long_output() as (hub, app, pilot, log):
            left = log.max_scroll_y
            log.scroll_to(y=_UP, animate=False, immediate=True)
            for line in range(_UP):
                hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"more {line}"))
            app.changed()
            await _eventually(pilot, lambda: log.max_scroll_y == left + _UP)
            log.scroll_to(y=left + 1, animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="and another"))
            app.changed()
            await _eventually(pilot, lambda: log.max_scroll_y > left + _UP)
            await pilot.pause(_PAINTED)

            held = (log.scroll_y, log.max_scroll_y)
        assert held[0] == left + 1
        assert held[1] > held[0]

    @staticmethod
    async def test_a_banner_pushing_the_end_down_keeps_the_follow():
        async with _long_output() as (hub, app, pilot, log):
            left = log.max_scroll_y
            hub.apply(
                DecideRequested(
                    cast_id="c1", request_id="q1", prompt="push?", options=["yes"]
                )
            )
            app.changed()
            await _eventually(pilot, lambda: log.max_scroll_y > left and _at_end(log))
            app.changed()
            await pilot.pause(_PAINTED)

            end = (log.scroll_y, log.max_scroll_y)
        assert end[0] == end[1]

    @staticmethod
    async def test_a_line_wider_than_the_pane_is_drawn_over_several_rows():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="wide " * 100))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="w" * 500))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            log = app.query_one("#log", Log)
            await _eventually(pilot, lambda: _at_end(log))

            rows = list(log.lines)
            width = log.scrollable_content_region.width
            sideways = (log.max_scroll_x, log.show_horizontal_scrollbar)
        assert "".join(rows) == "wide " * 100 + "w" * 500
        assert max(len(row) for row in rows) == width
        assert sideways == (0, False)

    @staticmethod
    async def test_a_resized_window_draws_the_rows_again_at_its_width():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="w" * 500))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            log = app.query_one("#log", Log)
            await _eventually(pilot, lambda: log.line_count > 1)
            before = len(log.lines[0])
            await pilot.resize_terminal(120, 24)
            await _eventually(pilot, lambda: len(log.lines[0]) != before)

            rows = list(log.lines)
            width = log.scrollable_content_region.width
        assert width > before
        assert "".join(rows) == "w" * 500
        assert len(rows[0]) == width

    @staticmethod
    async def test_a_pane_with_no_room_draws_nothing_until_it_has_room():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="w" * 500))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            log = app.query_one("#log", Log)
            await _eventually(pilot, lambda: log.line_count > 1)
            drawn = list(log.lines)
            await pilot.resize_terminal(4, 24)
            await pilot.pause(_PAINTED)
            narrow = (log.scrollable_content_region.width, list(log.lines))
            await pilot.resize_terminal(80, 24)
            await _eventually(pilot, lambda: len(log.lines) > 1)

            rows = list(log.lines)
        assert narrow[0] < 1
        assert narrow[1] == drawn
        assert "".join(rows) == "w" * 500

    @staticmethod
    async def test_a_pane_that_changed_only_in_height_does_not_cut_rows_again():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="w" * 500))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            log = app.query_one("#log", Log)
            await _eventually(pilot, lambda: log.line_count > 1)
            rows = list(log.lines)
            with patch.object(Text, "wrap", autospec=True) as wrap:
                await pilot.resize_terminal(80, 12)
                await pilot.pause(_PAINTED)

            after = list(log.lines)
        assert wrap.call_args_list == []
        assert after == rows

    @staticmethod
    async def test_a_pane_that_got_narrower_and_taller_keeps_following_the_end():
        async with _wrapping_output() as (hub, app, pilot, log):
            await pilot.resize_terminal(60, 40)
            await pilot.pause(_PAINTED)
            resized = (log.scroll_y, log.max_scroll_y)

            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="newest"))
            app.changed()
            await pilot.pause(_PAINTED)
            arrived = (log.scroll_y, log.max_scroll_y)
        assert resized[0] == resized[1]
        assert arrived[0] == arrived[1]
        assert arrived[1] == resized[1] + 1

    @staticmethod
    async def test_a_pane_that_got_narrower_and_taller_leaves_a_scrolled_up_reader():
        async with _wrapping_output() as (hub, app, pilot, log):
            log.scroll_to(y=log.max_scroll_y - _UP, animate=False, immediate=True)
            await pilot.pause(_PAINTED)
            await pilot.resize_terminal(60, 40)
            await pilot.pause(_PAINTED)
            resized = (log.scroll_y, log.max_scroll_y)

            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="newest"))
            app.changed()
            await pilot.pause(_PAINTED)
            arrived = (log.scroll_y, log.max_scroll_y)
        assert resized[0] < resized[1]
        assert arrived[0] < arrived[1]

    # Textual highlights the root of a tree it has just cleared, and that
    # highlight can land after the page is drawn.
    @staticmethod
    async def test_a_highlight_of_the_hidden_root_keeps_the_page():
        async with _long_output() as (_, app, pilot, log):
            tree: Tree[str] = app.query_one("#contents", Tree)
            log.scroll_to(y=_UP, animate=False, immediate=True)
            tree.post_message(Tree.NodeHighlighted(tree.root))
            await pilot.pause(_PAINTED)

            line = log.scroll_y
        assert line == _UP

    # An animated scroll starts within a rounding of the end.
    @staticmethod
    async def test_an_upward_scroll_that_has_only_begun_is_not_cancelled():
        async with _long_output() as (_, _, pilot, log):
            end = log.max_scroll_y
            log.scroll_to(y=end - _UP, animate=True, duration=30)
            await pilot.pause(_PAINTED)

            target = log.scroll_target_y
        assert target == end - _UP

    @staticmethod
    async def test_an_upward_scroll_begun_before_the_follow_lands_is_not_cancelled(
        monkeypatch: pytest.MonkeyPatch,
    ):
        async with _long_output() as (hub, app, pilot, log):
            drawn = log.line_count
            end = log.max_scroll_y
            after_refresh = log.call_after_refresh

            def scrolled_first(callback: Callable[..., object], *args: float) -> bool:
                if args:
                    monkeypatch.undo()
                    log.scroll_to(
                        y=end - _UP, animate=True, duration=30, immediate=True
                    )
                return after_refresh(callback, *args)

            monkeypatch.setattr(log, "call_after_refresh", scrolled_first)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one more"))
            app.changed()
            await _eventually(pilot, lambda: log.line_count != drawn)
            await pilot.pause(_PAINTED)

            target = log.scroll_target_y
        assert target == end - _UP


@pytest.mark.asyncio
class TestPages:
    @staticmethod
    async def test_a_ritual_page_lists_its_casts_with_their_flags():
        hub = Hub()
        hub.apply(
            _hello("c1abcdef9", "pr_fix").model_copy(update={"components": {"pr": 208}})
        )
        hub.apply(_hello("c2abcdef9", "pr_fix"))
        hub.apply(CastGoodbye(cast_id="c2abcdef9", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "r:/proj/.git:pr_fix")
            await pilot.pause(_PAINTED)

            head = _text(app, "#head").splitlines()
            _to(app, "f:r:/proj/.git:pr_fix")
            await pilot.pause(_PAINTED)

            finished = _text(app, "#head").splitlines()
        assert head[0] == "pr_fix"
        assert head[1].startswith("▶ @now      c1abcdef  running")
        assert head[1].endswith("  --pr 208")
        assert finished[0] == "pr_fix"
        assert finished[1].startswith("✓ @")

    @staticmethod
    async def test_a_project_page_says_where_it_is_and_what_it_holds():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        page = "proj\nmain · /proj\n1 running"

        async with app.run_test() as pilot:
            # First paint moves the cursor to the cast a refresh after drawing
            # the tree, undoing an earlier move.
            await _eventually(pilot, lambda: _cursor(app) == "c:c1")
            _to(app, "p:/proj/.git")

            await _eventually(pilot, lambda: _text(app, "#head") == page)

    @staticmethod
    async def test_with_no_casts_the_keys_say_there_is_nothing_here():
        app = _app(Hub(), [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space", "t")
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
            note = _text(app, "#note")
        assert head == "no cast here — c starts one"
        assert note == "only a running cast can be taken over"


@pytest.mark.asyncio
class TestCopying:
    @staticmethod
    async def test_text_dragged_over_is_copied_when_the_mouse_lets_go():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "check"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one two"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("space")
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            under_the_cast = log.region.y
            _to(app, "t:c1:r1")
            # The rite's head is shorter than the cast's, so the log moves up,
            # a layout pass after the head's text changes; a press aimed before
            # then lands below the first line.
            await _eventually(pilot, lambda: log.region.y < under_the_cast)
            await pilot.mouse_down("#log", offset=(0, 0))
            await pilot.hover("#log", offset=(2, 0))
            await pilot.mouse_up("#log", offset=(2, 0))
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
        assert app.clipboard == "one"
        assert note == "copied 3 characters"

    @staticmethod
    async def test_a_click_that_selects_nothing_copies_nothing():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.click("#log")
            await pilot.pause(_PAINTED)

            note = _text(app, "#note")
        assert not app.clipboard
        assert not note


@pytest.mark.asyncio
class TestSeen:
    @staticmethod
    async def test_s_takes_a_failed_cast_out_of_the_fails_and_s_again_puts_it_back():
        hub = Hub()
        hub.apply(_hello("c1abcdef9", "nap"))
        hub.apply(CastGoodbye(cast_id="c1abcdef9", status="error", detail="boom"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            loud = _contents(app)[0]
            await pilot.press("s")
            await pilot.pause(_PAINTED)
            quiet, marked = _contents(app)[0], _text(app, "#note")
            head = _text(app, "#head")
            glyph = _nodes(app)[3][1].label
            await pilot.press("s")
            await pilot.pause(_PAINTED)
            again, unmarked = _contents(app)[0], _text(app, "#note")

        assert loud == "proj (1 fail)"
        assert quiet == "proj"
        assert marked == "marked nap c1abcdef seen"
        assert "failed · seen" in head
        assert isinstance(glyph, Text)
        assert glyph.plain.startswith("✗ ")
        assert [str(span.style) for span in glyph.spans if span.start == 0] == ["dim"]
        assert again == "proj (1 fail)"
        assert unmarked == "unmarked nap c1abcdef"

    @staticmethod
    async def test_a_cast_that_did_not_fail_is_not_marked():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("s")
            await pilot.pause()
            note = _text(app, "#note")

        assert note == "only a failed cast can be marked seen"
        assert not hub.casts["c1"].seen


@pytest.mark.asyncio
class TestVigils:
    @staticmethod
    async def test_v_pauses_the_vigils_and_v_again_lets_them_cast():
        vigils = _Vigils()
        app = _vigil_app(vigils)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            before = _text(app, "#scope")
            await pilot.press("v")
            await pilot.pause(_PAINTED)
            paused, said = _text(app, "#scope"), _text(app, "#note")
            await pilot.press("v")
            await pilot.pause(_PAINTED)
            after, said_after = _text(app, "#scope"), _text(app, "#note")

        assert before == "no casts  (proj)"
        assert paused == "vigils paused · no casts  (proj)"
        assert said == (
            "vigils paused — what runs carries on, and v lets them cast again"
        )
        assert after == "no casts  (proj)"
        assert said_after == "vigils cast again"
        assert vigils.asked == [None, True, False]

    @staticmethod
    async def test_a_window_opened_on_paused_vigils_says_so_and_v_lets_them_cast():
        vigils = _Vigils(paused=True)
        app = _vigil_app(vigils)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            opened = _text(app, "#scope")
            await pilot.press("v")
            await pilot.pause(_PAINTED)
            after = _text(app, "#scope")

        assert opened == "vigils paused · no casts  (proj)"
        assert after == "no casts  (proj)"
        assert vigils.asked == [None, False]

    @staticmethod
    async def test_a_pause_another_window_made_shows_at_the_next_look():
        vigils = _Vigils()
        with patch("vekna.gates.cli.tui._VIGILS_SECONDS", 0.05):
            app = _vigil_app(vigils)

            async with app.run_test() as pilot:
                await pilot.pause(_PAINTED)
                vigils.paused = True
                await pilot.pause(_PAINTED)
                scope = _text(app, "#scope")

        assert scope == "vigils paused · no casts  (proj)"
        assert set(vigils.asked) == {None}

    @staticmethod
    async def test_a_daemon_that_does_not_say_leaves_the_vigils_as_they_were():
        vigils = _Vigils(said=False)
        app = _vigil_app(vigils)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("v")
            await pilot.pause(_PAINTED)
            scope, said = _text(app, "#scope"), _text(app, "#note")

        assert scope == "no casts  (proj)"
        assert said == (
            "the daemon did not say whether its vigils are paused: it is gone,"
            " or it predates pausing them"
        )
        assert vigils.asked == [None, True]
