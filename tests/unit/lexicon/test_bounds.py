import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from tests.conftest import entry
from vekna.lexicon import (
    Done,
    Failure,
    MediumBoundaryError,
    RiteTimeoutError,
    RitualDefinitionError,
    RitualError,
    medium,
    race,
    step,
    timeout,
)
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast
from vekna.lexicon._pacts import RiteBegan, RiteEnded


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


@medium
async def nap(seconds: float) -> str:
    await asyncio.sleep(seconds)
    return "woke"


@medium
async def stall() -> str:
    await asyncio.sleep(0)
    raise TimeoutError


class Slow(BaseModel):
    pass


class Bounded(BaseModel):
    pass


class Recovered(BaseModel):
    message: str
    attempt: int


class Unrouted(BaseModel):
    pass


class OwnTimeout(BaseModel):
    pass


@step
async def slow(_: Slow) -> Done[str]:
    return Done(await timeout(nap(60), seconds=0.01))


@step(timeout=0.01)
async def bounded(_: Bounded) -> Done[str]:
    return Done(await nap(60))


@step
def recover(failure: Failure[Bounded]) -> Done[Recovered]:
    return Done(Recovered(message=failure.error.message, attempt=failure.attempt))


@step(timeout=0.01)
async def unrouted(_: Unrouted) -> Done[str]:
    return Done(await nap(60))


@step
async def own_timeout(_: OwnTimeout) -> Done[str]:
    return Done(await timeout(stall(), seconds=60))


def _cast(payload: BaseModel) -> tuple[BaseModel | None, Grimoire]:
    grimoire = Grimoire(clock=_fixed_clock)
    the_ritual = entry(payload=payload)
    result = asyncio.run(
        run_cast(
            ritual=the_ritual,
            components=the_ritual.components(),
            grimoire=grimoire,
            channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
        )
    )
    return result, grimoire


def _statuses(grimoire: Grimoire) -> list[tuple[str, str]]:
    names = {
        event.rite_id: event.name
        for event in grimoire.events
        if isinstance(event, RiteBegan)
    }
    return [
        (names[event.rite_id], event.status)
        for event in grimoire.events
        if isinstance(event, RiteEnded)
    ]


class TestTimeout:
    @staticmethod
    def test_an_overrun_cancels_the_rite_and_names_it():
        with pytest.raises(RiteTimeoutError, match=r"^nap timed out after 0\.01s$"):
            _cast(Slow())

    @staticmethod
    def test_the_cut_rite_reads_cancelled_and_its_step_failed():
        grimoire = Grimoire(clock=_fixed_clock)
        the_ritual = entry(payload=Slow())

        with pytest.raises(RiteTimeoutError):
            asyncio.run(
                run_cast(
                    ritual=the_ritual,
                    components=the_ritual.components(),
                    grimoire=grimoire,
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                )
            )

        assert _statuses(grimoire) == [("nap", "cancelled"), ("slow", "error")]

    @staticmethod
    def test_a_timeout_the_work_raised_itself_is_not_the_deadline():
        with pytest.raises(TimeoutError) as raised:
            _cast(OwnTimeout())

        assert not isinstance(raised.value, RiteTimeoutError)

    @staticmethod
    def test_seconds_must_be_positive():
        async def bad() -> str:
            return await timeout(asyncio.sleep(0, result="x"), seconds=0)

        with pytest.raises(
            MediumBoundaryError, match="positive number of seconds, got 0"
        ):
            asyncio.run(bad())

    @staticmethod
    def test_refused_work_that_is_no_coroutine_is_left_as_it_came():
        async def refused() -> asyncio.Future[str]:
            work: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            with pytest.raises(
                MediumBoundaryError, match="positive number of seconds, got -1"
            ):
                await timeout(work, seconds=-1)
            return work

        assert not asyncio.run(refused()).done()

    # Outside a cast the coroutine itself is the name: `asyncio.sleep` here.
    @staticmethod
    def test_an_overrun_outside_a_rite_names_the_coroutine():
        with pytest.raises(RiteTimeoutError, match=r"^sleep timed out after 0\.01s$"):
            asyncio.run(timeout(asyncio.sleep(1), seconds=0.01))

    @staticmethod
    def test_an_overrun_of_work_that_is_no_coroutine_names_the_work():
        async def overrun() -> None:
            await timeout(asyncio.ensure_future(asyncio.sleep(1)), seconds=0.01)

        with pytest.raises(
            RiteTimeoutError, match=r"^the work timed out after 0\.01s$"
        ):
            asyncio.run(overrun())


class TestStepTimeout:
    @staticmethod
    def test_an_overrun_is_a_failure_a_step_can_take():
        result, grimoire = _cast(Bounded())

        assert result == Recovered(
            message="step 'bounded' timed out after 0.01s", attempt=1
        )
        assert _statuses(grimoire) == [
            ("nap", "cancelled"),
            ("bounded", "error"),
            ("recover", "ok"),
        ]

    @staticmethod
    def test_with_no_route_the_cast_ends_naming_the_step():
        with pytest.raises(
            RiteTimeoutError, match=r"^step 'unrouted' timed out after 0\.01s$"
        ):
            _cast(Unrouted())

    @staticmethod
    def test_a_timeout_must_be_positive():
        with pytest.raises(RitualDefinitionError, match="timeout must be positive"):
            step(timeout=0)


async def _gives_up() -> str:
    await asyncio.sleep(0)
    raise asyncio.CancelledError


async def _falls() -> str:
    await asyncio.sleep(0)
    msg = "fell"
    raise RitualError(msg)


class TestRace:
    # The loser is awaited out, not just asked to stop: it reads cancelled by
    # the time the winner comes back.
    @staticmethod
    def test_the_winner_returns_once_the_loser_is_cancelled():
        async def run() -> tuple[str, bool]:
            loser = asyncio.ensure_future(asyncio.sleep(1, result="slow"))
            won = await race(loser, asyncio.sleep(0, result="fast"))
            return won, loser.cancelled()

        assert asyncio.run(run()) == ("fast", True)

    @staticmethod
    def test_a_cancelled_entrant_is_named_among_the_failures():
        with pytest.raises(
            RitualError,
            match=r"^every entrant in the race failed — cancelled; RitualError: fell$",
        ):
            asyncio.run(race(_gives_up(), _falls()))

    @staticmethod
    def test_a_race_with_no_entrants_is_refused():
        with pytest.raises(
            MediumBoundaryError, match=r"^race needs at least one entrant$"
        ):
            asyncio.run(race())
