import asyncio
from datetime import UTC, datetime

import pytest
from textual.widgets import DataTable, Log, Static, Tree
from textual.widgets.tree import TreeNode

from vekna.gates.cli.tui import AnswerScreen, VeknaApp
from vekna.mills.hub import Hub
from vekna.wire import (
    CastCancelRequested,
    CastGoodbye,
    CastHello,
    CastRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    TreeBlocked,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)
_PAINTED = 0.3


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


def _asking(hub: Hub) -> None:
    hub.apply(_hello("c1", "pr_fix"))
    hub.apply(
        DecideRequested(
            cast_id="c1", request_id="q1", prompt="push?", options=["yes", "no"]
        )
    )


# The app over `hub`, keeping what it sends; branches are answered by root.
def _app(hub: Hub, sent: list[WireMessage]) -> VeknaApp:
    branches = {"/proj": "main", "/trees/1": "fix-ci"}

    async def branch_of(root: str) -> str | None:
        await asyncio.sleep(0)
        return branches.get(root)

    return VeknaApp(
        casts=hub,
        project="/proj/.git",
        root="/proj",
        send=sent.append,
        branch_of=branch_of,
    )


def _cells(app: VeknaApp) -> list[list[str]]:
    table = app.query_one("#casts", DataTable)
    return [[str(cell) for cell in table.get_row(key)] for key in table.rows]


def _text(app: VeknaApp, selector: str) -> str:
    return str(app.query_one(selector, Static).render())


def _rites(app: VeknaApp) -> list[str]:
    tree: Tree[str | None] = app.query_one("#rites", Tree)
    found: list[str] = []

    def walk(node: TreeNode[str | None], depth: int) -> None:
        for child in node.children:
            found.append("  " * depth + str(child.label))
            walk(child, depth + 1)

    walk(tree.root, 0)
    return found


def _claim_then(sent: list[WireMessage]) -> DecideClaimed:
    claim = sent[0]
    assert isinstance(claim, DecideClaimed)
    assert claim.claim_id
    return claim


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
class TestListing:
    @staticmethod
    async def test_a_queued_cast_sits_under_the_cast_that_queued_it():
        hub = Hub()
        hub.apply(_hello("c1abcdef9", "sweep"))
        hub.apply(_hello("c2abcdef9", "ci_watch"))
        hub.apply(
            _hello("c3abcdef9", "pr_fix").model_copy(
                update={"enqueued_by": "c1abcdef9"}
            )
        )
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            rows = _cells(app)
        assert [row[1] for row in rows] == ["sweep", "└ pr_fix", "ci_watch"]

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
    async def test_the_cast_under_the_cursor_shows_its_rites_as_a_tree():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        hub.apply(_rite("r2", "coding", parent="r1"))
        hub.apply(RiteDelta(cast_id="c1", rite_id="r2", delta="[red] check"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            rites = _rites(app)
            head = _text(app, "#head")
            output = "\n".join(app.query_one("#log", Log).lines)
        assert [line.rsplit("  ", 1)[0] for line in rites] == ["▶ watch", "  ▶ coding"]
        assert output == "[red] check"
        assert "main · /proj" in head

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

            rites = _rites(app)
        assert rites == ["✗ watch  0s  gh failed"]

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
        hub.apply(CastGoodbye(cast_id="c1", status="error", detail="boom\ntrace"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
        assert output == ["boom", "trace"]

    @staticmethod
    async def test_the_cursor_stays_on_its_cast_when_another_arrives():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            hub.apply(_hello("c2", "sweep"))
            app.changed()
            await pilot.pause(_PAINTED)

            rows = _cells(app)
            head = _text(app, "#head")
        assert sorted(row[1] for row in rows) == ["nap", "sweep"]
        assert head.startswith("nap  c1")

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
            tree: Tree[str | None] = app.query_one("#rites", Tree)
            tree.move_cursor(tree.root.children[0])
            await pilot.pause(_PAINTED)
            hub.apply(_rite("r3", "third"))
            app.changed()
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
            picked = tree.cursor_node
        assert output == ["one"]
        assert picked is not None
        assert picked.data == "r1"

    @staticmethod
    async def test_g_shows_every_project_and_p_goes_back_home():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("g")
            await pilot.pause(_PAINTED)
            every = (app.sub_title, _cells(app)[0][1])
            await pilot.press("p")
            await pilot.pause(_PAINTED)

            home = (app.sub_title, _cells(app)[0][1])
        assert every == ("1 running  (all projects)", "proj:nap")
        assert home == ("1 running  (proj)", "nap")

    @staticmethod
    async def test_a_cast_scoped_away_takes_its_rites_with_it():
        hub = Hub()
        hub.apply(
            _hello("c1", "ci_watch").model_copy(update={"project": "/other/.git"})
        )
        hub.apply(_rite("r1", "watch"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.press("g")
            await pilot.pause(_PAINTED)
            every = _rites(app)
            await pilot.press("p")
            await pilot.pause(_PAINTED)

            home = _rites(app)
        assert [line.rsplit("  ", 1)[0] for line in every] == ["▶ watch"]
        assert not home


@pytest.mark.asyncio
class TestWaiting:
    @staticmethod
    async def test_the_question_is_a_banner_and_a_node_under_the_rite_that_asked():
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
            rites = _rites(app)
        assert ask == "⏸ push?\n  yes | no · open · t answers it"
        assert rites[1] == "  ⏸ push?"

    @staticmethod
    async def test_w_moves_to_the_cast_waiting_on_the_operator():
        hub = Hub()
        hub.apply(_hello("c2", "ci_watch"))
        _asking(hub)
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            table = app.query_one("#casts", DataTable)
            table.move_cursor(row=1)
            await pilot.pause(_PAINTED)
            pointer = _text(app, "#ask")
            await pilot.press("w")
            await pilot.pause(_PAINTED)

            ask = _text(app, "#ask")
        assert pointer == "⏸ 1 cast waits on you · w goes to it"
        assert ask.startswith("⏸ push?")

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
        assert ask == "⏸ push?\n  yes | no · claimed elsewhere · t answers it"


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

            title = app.sub_title
        assert title == "no casts  (all projects)"

    @staticmethod
    async def test_t_typed_takes_the_prompt_over():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("c", "ctrl+u", "t", "enter")
            await pilot.pause()

            screen = app.screen
        assert isinstance(screen, AnswerScreen)
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


@pytest.mark.asyncio
class TestTakingOver:
    @staticmethod
    async def test_t_claims_the_prompt_and_the_dialog_answers_it():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            assert isinstance(app.screen, AnswerScreen)
            await pilot.click("#choice-1")
            await pilot.pause()

        claim = _claim_then(sent)
        assert sent == [
            DecideClaimed(cast_id="c1", request_id="q1", claim_id=claim.claim_id),
            DecideResolved(cast_id="c1", request_id="q1", answer="no"),
        ]

    @staticmethod
    async def test_a_free_prompt_takes_an_answer_typed_into_the_dialog():
        hub = Hub()
        hub.apply(_hello("c1", "pr_fix"))
        hub.apply(
            DecideRequested(cast_id="c1", request_id="q1", prompt="why?", free=True)
        )
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            await pilot.click("#free")
            await pilot.press(*"flaky", "enter")
            await pilot.pause()

        claim = _claim_then(sent)
        assert sent == [
            claim,
            DecideResolved(cast_id="c1", request_id="q1", answer="flaky"),
        ]

    @staticmethod
    async def test_escape_lets_the_claim_go():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

        claim = _claim_then(sent)
        assert sent == [
            claim,
            DecideClaimed(cast_id="c1", request_id="q1", claim_id=None),
        ]

    @staticmethod
    async def test_a_prompt_answered_elsewhere_closes_its_dialog():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
            app.changed()
            await pilot.pause(_PAINTED)

            assert not isinstance(app.screen, AnswerScreen)
        assert sent == [_claim_then(sent)]

    # The palette is a screen of its own: closing whatever is on top would
    # close it and leave the dialog up for a prompt that has gone.
    @staticmethod
    async def test_a_dialog_under_the_palette_still_closes_when_its_prompt_goes():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            app.action_command_palette()
            await pilot.pause()
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
            app.changed()
            await pilot.pause(_PAINTED)

            stack = app.screen_stack
        assert not any(isinstance(screen, AnswerScreen) for screen in stack)
        assert len(stack) == 1
        assert sent == [_claim_then(sent)]

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
    async def test_with_nothing_waiting_t_says_so():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()

            note = _text(app, "#note")
        assert not sent
        assert note == "nothing to answer — pick a waiting cast first"


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
