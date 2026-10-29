import asyncio
from datetime import UTC, datetime

import pytest
from textual.widgets import Log, Static, Tree
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
        hub.apply(
            _hello("c3abcdef9", "pr_fix").model_copy(
                update={"enqueued_by": "c1abcdef9"}
            )
        )
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
            await pilot.press("e")
            await pilot.pause(_PAINTED)

            lines = _contents(app)
        assert [line.rsplit("  ", 1)[0] for line in lines[3:]] == [
            "      ▶ watch",
            "        ▶ coding",
            "      ▶ shell",
        ]

    @staticmethod
    async def test_a_cast_that_ended_still_asking_stays_in_the_running_ones():
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
    async def test_every_cast_shows_on_e_and_the_running_ones_again_on_a_second():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        hub.apply(_hello("c2", "sweep"))
        hub.apply(CastGoodbye(cast_id="c2", status="ok"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            running = _contents(app)
            await pilot.press("e")
            await pilot.pause(_PAINTED)
            every = _contents(app)
            await pilot.press("e")
            await pilot.pause(_PAINTED)

            again = _contents(app)
        assert running == ["proj (1 running)", "  nap", "    ▶ @now  c1"]
        assert every[3:5] == ["  sweep", every[4]]
        assert every[4].startswith("    ✓ @")
        assert every[4].endswith("  c2")
        assert again == running

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
            await pilot.press("e")
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
            await pilot.press("e")
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
            await pilot.press("e")
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
            await pilot.press("e")
            await pilot.pause(_PAINTED)
            _to(app, "t:c1:r1")
            await pilot.pause(_PAINTED)

            output = list(app.query_one("#log", Log).lines)
        assert output == ["one", " ", "two"]

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
            await pilot.press("e")
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
            every = (app.sub_title, _contents(app)[::3])
            await pilot.press("p")
            await pilot.pause(_PAINTED)

            home = (app.sub_title, _contents(app)[::3])
        assert every == (
            "2 running  (all projects)",
            ["other (1 running)", "proj (1 running)"],
        )
        assert home == ("1 running  (proj)", ["proj (1 running)"])


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
    async def test_a_failure_stays_until_its_cast_has_been_opened_and_left():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(CastGoodbye(cast_id="c1", status="error"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            unseen = _contents(app)
            opened = _cursor(app)
            app.changed()
            await pilot.pause(_PAINTED)
            reading = _contents(app)
            _to(app, "p:/proj/.git")
            await pilot.pause(_PAINTED)

            left = _contents(app)
        assert unseen[:2] == ["proj (1 fail)", "  ci_watch"]
        assert unseen[2].startswith("    ✗ @")
        assert unseen[2].endswith("  c1")
        assert opened == "c:c1"
        assert reading == unseen
        assert left == ["proj"]

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
        assert ask == "⏸ push?\n  yes | no · open · t answers it"
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


@pytest.mark.asyncio
class TestFollowing:
    @staticmethod
    async def test_the_output_ends_on_the_newest_line_as_more_arrives():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        for line in range(100):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            first = (log.scroll_y, log.max_scroll_y)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="newest"))
            app.changed()
            await pilot.pause(_PAINTED)

            then = (log.scroll_y, log.max_scroll_y)
        assert first[1] > 0
        assert first[0] == first[1]
        assert then[0] == then[1]

    @staticmethod
    async def test_scrolling_up_stops_the_follow_and_the_end_starts_it_again():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        for line in range(100):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            log.scroll_to(y=_UP, animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="one more"))
            app.changed()
            await pilot.pause(_PAINTED)
            held = log.scroll_y
            log.scroll_end(animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="and another"))
            app.changed()
            await pilot.pause(_PAINTED)

            again = (log.scroll_y, log.max_scroll_y)
        assert held == _UP
        assert again[0] == again[1]

    # Past where the follow last left the end, but short of the new one.
    @staticmethod
    async def test_scrolling_down_short_of_the_end_keeps_the_follow_stopped():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        for line in range(100):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            left = log.max_scroll_y
            log.scroll_to(y=_UP, animate=False, immediate=True)
            for line in range(_UP):
                hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"more {line}"))
            app.changed()
            await pilot.pause(_PAINTED)
            log.scroll_to(y=left + 1, animate=False, immediate=True)
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="and another"))
            app.changed()
            await pilot.pause(_PAINTED)

            held = (log.scroll_y, log.max_scroll_y)
        assert held[0] == left + 1
        assert held[1] > held[0]

    @staticmethod
    async def test_a_banner_pushing_the_end_down_keeps_the_follow():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(_rite("r1", "watch"))
        for line in range(100):
            hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta=f"line {line}"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            log = app.query_one("#log", Log)
            hub.apply(
                DecideRequested(
                    cast_id="c1", request_id="q1", prompt="push?", options=["yes"]
                )
            )
            app.changed()
            await pilot.pause(_PAINTED)
            app.changed()
            await pilot.pause(_PAINTED)

            end = (log.scroll_y, log.max_scroll_y)
        assert end[0] == end[1]


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
        assert head[0] == "pr_fix"
        assert head[1].startswith("▶ @now      c1abcdef  running")
        assert head[1].endswith("  --pr 208")
        assert head[2].startswith("✓ @")

    @staticmethod
    async def test_a_project_page_says_where_it_is_and_what_it_holds():
        hub = Hub()
        hub.apply(_hello("c1", "nap"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            _to(app, "p:/proj/.git")
            await pilot.pause(_PAINTED)

            head = _text(app, "#head")
        assert head == "proj\nmain · /proj\n1 running"

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
        assert note == "nothing to answer — pick a waiting cast first"
