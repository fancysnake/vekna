import os
from pathlib import Path

from vekna.lexicon._pacts import Resumption, RitualDefinitionError
from vekna.wire import RunRecord, WireMessage, decode_frame

_EVENTS = "events.jsonl"
_RUN = "run.json"
_RUNS_ENV = "VEKNA_RUNS"


# The same directory the daemon writes to, computed twice because a cast process
# may not import the daemon's layers — the same split that has the socket path
# written in two places. Both read `VEKNA_RUNS` first.
def default_runs_root() -> Path:
    if (named := os.environ.get(_RUNS_ENV)) is not None:
        return Path(named)
    return Path.home() / ".config" / "vekna" / "runs"


def _events(directory: Path) -> list[WireMessage]:
    log = directory / _EVENTS
    if not log.is_file():
        return []
    with log.open("rb") as events:
        return [decode_frame(frame) for frame in events if frame.strip()]


# A cast with no journal is a cast that ran with no daemon listening, and the
# answer to "resume it" is that there is nothing to resume from — said as a
# sentence naming the directory that is not there.
def read_run(cast_id: str, *, root: Path | None = None) -> Resumption:
    directory = (root if root is not None else default_runs_root()) / cast_id
    run = directory / _RUN
    if not run.is_file():
        msg = (
            f"no journal for cast {cast_id!r} at {directory}"
            " — only a cast the daemon saw can be resumed"
        )
        raise RitualDefinitionError(msg)
    record = RunRecord.model_validate_json(run.read_text())
    return Resumption(record=record, events=_events(directory))
