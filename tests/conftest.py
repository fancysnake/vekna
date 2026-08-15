import io
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, JsonValue

from vekna.lexicon import NoComponents, Transition, goto, ritual
from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import Resumption, Ritual, Step
from vekna.wire import CastHello, RiteFinished, RiteStarted, RunRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


# A notification is an escape sequence written only to a tty, and neither
# pytest's capture nor a plain StringIO is one. Both suites need a stream that
# says it is a terminal.
class Tty(io.StringIO):
    @staticmethod
    def isatty() -> bool:
        return True


# Most tests need a ritual only to reach the step they are actually about — an
# entrypoint that names one target and hands it a payload, which written out is
# the same three lines every time. `name` stays a parameter because it reaches
# the rendered rite tree, so a test asserting on output still gets to say what
# the ritual is called.
def entry(*, name: str = "r", target: Step, payload: BaseModel) -> Ritual:
    @ritual(name)
    def _enter(_: NoComponents) -> Transition:
        return goto(target, payload)

    return _enter


# One recorded medium rite, as the daemon would have journalled it — which is
# all a resumed cast reads. `rite_id` is a counter in the cast being resumed, so
# "r2" is the first medium inside the first step.
def journalled(
    result: JsonValue,
    *,
    rite_id: str = "r2",
    name: str,
    status: Literal["ok", "error"] = "ok",
) -> Ledger:
    return Ledger.from_resumption(
        Resumption(
            record=RunRecord(
                hello=CastHello(
                    cast_id="c0",
                    project_root="/proj",
                    ritual="job",
                    components={},
                    started_at=_WHEN,
                )
            ),
            events=[
                RiteStarted(
                    cast_id="c0",
                    rite_id=rite_id,
                    parent_id=None,
                    name=name,
                    category="medium",
                    started_at=_WHEN,
                ),
                RiteFinished(
                    cast_id="c0",
                    rite_id=rite_id,
                    status=status,
                    result=result,
                    finished_at=_WHEN,
                ),
            ],
        )
    )
