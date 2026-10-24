import asyncio
from datetime import UTC, datetime

import pytest
from textual.widgets import DataTable, Static

from vekna.gates.cli.tui import AnswerScreen, VeknaApp
from vekna.mills.hub import Hub
from vekna.wire import (
    CastHello,
    CastRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    RiteDelta,
    RiteStarted,
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


def _pane(app: VeknaApp) -> str:
    return str(app.query_one("#detail", Static).render())


def _note(app: VeknaApp) -> str:
    return str(app.query_one("#note", Static).render())


def _claim_then(sent: list[WireMessage]) -> DecideClaimed:
    claim = sent[0]
    assert isinstance(claim, DecideClaimed)
    assert claim.claim_id
    return claim


@pytest.mark.asyncio
class TestListing:
    @staticmethod
    async def test_each_cast_shows_its_branch_and_where_it_runs():
        hub = Hub()
        hub.apply(_hello("c1abcdef9", "ci_watch"))
        hub.apply(_hello("c2abcdef9", "pr_fix", root="/trees/1"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            rows = _cells(app)
        assert [row[2] for row in rows] == ["ci_watch", "pr_fix"]
        assert [(row[7], row[8]) for row in rows] == [
            ("main", "/proj"),
            ("fix-ci", "/trees/1"),
        ]

    @staticmethod
    async def test_the_cast_under_the_cursor_streams_in_the_pane():
        hub = Hub()
        hub.apply(_hello("c1", "ci_watch"))
        hub.apply(
            RiteStarted(
                cast_id="c1",
                rite_id="r1",
                parent_id=None,
                name="watch",
                category="step",
                started_at=_WHEN,
            )
        )
        hub.apply(RiteDelta(cast_id="c1", rite_id="r1", delta="[red] check"))
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)

            pane = _pane(app)
        assert "▶ watch" in pane
        assert "[red] check" in pane
        assert "branch main · in /proj" in pane


@pytest.mark.asyncio
class TestCommands:
    @staticmethod
    async def test_c_asks_the_daemon_for_a_cast_here():
        sent: list[WireMessage] = []
        app = _app(Hub(), sent)

        async with app.run_test() as pilot:
            await pilot.press("c", *"sweep --max-prs 1", "enter")
            await pilot.pause(_PAINTED)

            note = _note(app)
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

            note = _note(app)
        assert note.startswith("'zap' means nothing here")


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
        app = _app(hub, [])

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("t")
            await pilot.pause()
            hub.apply(DecideResolved(cast_id="c1", request_id="q1", answer="yes"))
            app.changed()
            await pilot.pause(_PAINTED)

            assert not isinstance(app.screen, AnswerScreen)

    @staticmethod
    async def test_a_answers_with_a_claim_and_refuses_what_is_not_offered():
        hub = Hub()
        _asking(hub)
        sent: list[WireMessage] = []
        app = _app(hub, sent)

        async with app.run_test() as pilot:
            await pilot.pause(_PAINTED)
            await pilot.press("a", *"maybe", "enter")
            await pilot.pause()
            refused = _note(app)
            await pilot.press("a", *"yes", "enter")
            await pilot.pause()

        assert refused == "'maybe' is not one of yes, no"
        claim = _claim_then(sent)
        assert sent == [
            claim,
            DecideResolved(cast_id="c1", request_id="q1", answer="yes"),
        ]

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

            note = _note(app)
        assert not sent
        assert note == "nothing to answer — pick a waiting cast first"
