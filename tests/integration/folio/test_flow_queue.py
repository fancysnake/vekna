import asyncio
import io
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, JsonValue

from tests.conftest import entry, journalled
from vekna.folio.flow import await_cast, enqueue
from vekna.lexicon import CAST_QUEUE, CastFailedError, Done, RitualError, step
from vekna.lexicon._links.standalone import StandaloneRenderer
from vekna.lexicon._mills.engine import Grimoire, run_cast
from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import Resumption
from vekna.trial import Enqueued, QueueDouble, Trial
from vekna.trial._mills import Script
from vekna.wire import CastHello, RiteFinished, RiteStarted, RunRecord, WireMessage

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


class Sweep(BaseModel):
    pull_request: int


class Fixed(BaseModel):
    commits: int


class Sweeping(BaseModel):
    pass


class Fanning(BaseModel):
    pass


class Loose(BaseModel):
    pass


class Swept(BaseModel):
    fixed: int


class Queued(BaseModel):
    cast_ids: list[str]


@step
async def sweep(_: Sweeping) -> Done[Swept]:
    fixed = await await_cast("refresh", Sweep(pull_request=7), output=Fixed)
    return Done(Swept(fixed=fixed.commits))


@step
async def fan_out(_: Fanning) -> Done[Queued]:
    return Done(
        Queued(
            cast_ids=[await enqueue("refresh", Sweep(pull_request=n)) for n in (1, 2)]
        )
    )


@step
async def loose(_: Loose) -> Done[Swept]:
    result = await await_cast("refresh", Sweep(pull_request=7))
    assert isinstance(result, dict)
    commits = result["commits"]
    assert isinstance(commits, int)
    return Done(Swept(fixed=commits))


class TestAwaitCast:
    @staticmethod
    def test_the_child_s_result_comes_back_as_the_model_asked_for(trial: Trial):
        trial.queue.returns(Fixed(commits=3), when="refresh")

        result = trial.walk(sweep, Sweeping())

        assert result == Done(Swept(fixed=3))
        assert trial.queue.enqueued == [
            Enqueued(cast_id="c1", ritual="refresh", components=Sweep(pull_request=7))
        ]

    @staticmethod
    def test_with_no_output_the_result_is_the_json_it_was(trial: Trial):
        trial.queue.returns(Fixed(commits=4))

        assert trial.walk(loose, Loose()) == Done(Swept(fixed=4))

    @staticmethod
    def test_a_child_that_failed_fails_the_step_saying_why(trial: Trial):
        trial.queue.fails("tests are red")

        with pytest.raises(CastFailedError, match="cast c1 ended error: tests are red"):
            trial.walk(sweep, Sweeping())

    @staticmethod
    def test_a_result_that_is_not_the_model_asked_for_is_refused(trial: Trial):
        trial.queue.returns(Sweep(pull_request=1))

        with pytest.raises(RitualError, match="cast c1 returned what does not"):
            trial.walk(sweep, Sweeping())


class TestEnqueue:
    @staticmethod
    def test_enqueueing_needs_no_script_and_proceeds(trial: Trial):
        result = trial.walk(fan_out, Fanning())

        assert result == Done(Queued(cast_ids=["c1", "c2"]))
        assert trial.queue.rituals == ["refresh", "refresh"]

    # A resumed cast that had enqueued already gets the id it was given.
    @staticmethod
    def test_a_resumed_cast_does_not_queue_its_child_again():
        queue = QueueDouble(Script(kind="await_cast"))
        ritual = entry(payload=Fanning())

        with CAST_QUEUE.scope(queue):
            result = asyncio.run(
                run_cast(
                    ritual=ritual,
                    components=ritual.components(),
                    grimoire=Grimoire(),
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                    ledger=journalled("c9", name="enqueue"),
                )
            )

        assert result == Queued(cast_ids=["c9", "c1"])
        assert queue.rituals == ["refresh"]

    @staticmethod
    def test_a_journaled_id_that_is_not_text_is_refused():
        ritual = entry(payload=Fanning())

        with pytest.raises(RitualError, match="journaled cast id 7 is not text"):
            asyncio.run(
                run_cast(
                    ritual=ritual,
                    components=ritual.components(),
                    grimoire=Grimoire(),
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                    ledger=journalled(7, name="enqueue"),
                )
            )


def _replayed(*rites: tuple[str, str, JsonValue]) -> Ledger:
    hello = CastHello(
        cast_id="c0",
        project_root="/proj",
        project="/proj/.git",
        ritual="job",
        components={},
        started_at=_WHEN,
    )
    events: list[WireMessage] = []
    for rite_id, name, result in rites:
        events.extend(
            (
                RiteStarted(
                    cast_id="c0",
                    rite_id=rite_id,
                    parent_id="r1",
                    name=name,
                    category="medium",
                    started_at=_WHEN,
                ),
                RiteFinished(
                    cast_id="c0",
                    rite_id=rite_id,
                    status="ok",
                    result=result,
                    finished_at=_WHEN,
                ),
            )
        )
    return Ledger.from_resumption(
        Resumption(record=RunRecord(hello=hello), events=events)
    )


class TestResumedAwait:
    # The child ended before the interruption: its result comes off the record,
    # and the daemon is not asked again.
    @staticmethod
    def test_a_wait_that_finished_is_not_waited_again():
        queue = QueueDouble(Script(kind="await_cast"))
        ritual = entry(payload=Sweeping())

        with CAST_QUEUE.scope(queue):
            result = asyncio.run(
                run_cast(
                    ritual=ritual,
                    components=ritual.components(),
                    grimoire=Grimoire(),
                    channel=StandaloneRenderer(out=io.StringIO(), inp=io.StringIO()),
                    ledger=_replayed(
                        ("r2", "enqueue", "c9"), ("r3", "awaited", {"commits": 5})
                    ),
                )
            )

        assert result == Swept(fixed=5)
        assert not queue.enqueued
