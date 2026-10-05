import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from tests.conftest import entry
from vekna.lexicon import (
    Done,
    Failure,
    RiteTimeoutError,
    RitualDefinitionError,
    RitualError,
    medium,
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
    grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
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
        grimoire = Grimoire(cast_id="c1", clock=_fixed_clock)
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

        with pytest.raises(RitualError, match="positive number of seconds, got 0"):
            asyncio.run(bad())


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
