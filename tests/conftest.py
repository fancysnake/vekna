import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, JsonValue

from vekna.lexicon import NoComponents, Transition, goto, ritual
from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import Resumption, Ritual, Step
from vekna.wire import CastHello, RiteFinished, RiteStarted, RunRecord

_WHEN = datetime(2026, 1, 1, tzinfo=UTC)


# A cast with nothing said to it dials `$XDG_RUNTIME_DIR/vekna.sock` and writes
# to `~/.local/state/vekna/runs`, which is the operator's own daemon and the
# operator's own journal: a suite run beside a live `vekna` fills their
# dashboard with test casts. Every test gets its own instead — one that is
# *about* the default path unsets these itself. `XDG_STATE_HOME` is here too
# because the debug log hangs off it and `VEKNA_RUNS` does not cover it.
@pytest.fixture(autouse=True)
def _own_runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # The global config is `$XDG_CONFIG_HOME/vekna` and `~/.config/vekna` only
    # when nothing exports one, and the tests that check it move `HOME`. Cleared
    # so the suite reads the same on a machine that sets it as on one that does
    # not — the test that is about the variable sets it itself.
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


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
