from pathlib import Path

from vekna.lexicon._pacts import Resumption, RitualDefinitionError
from vekna.wire import (
    RunRecord,
    WireMessage,
    default_runs_root,
    events_log,
    read_events,
    read_record,
    run_file,
)


# A cast with no journal is a cast that ran with no daemon listening, and the
# answer to "resume it" is that there is nothing to resume from — said as a
# sentence naming the directory that is not there.
def read_run(cast_id: str, *, root: Path | None = None) -> Resumption:
    where = root if root is not None else default_runs_root()
    if (record := _record(where, cast_id)) is None:
        run = run_file(where, cast_id)
        msg = (
            f"no journal for cast {cast_id!r} at {run.parent}"
            " — only a cast the daemon saw can be resumed"
        )
        raise RitualDefinitionError(msg)
    return Resumption(record=record, events=_events(where, cast_id))


# The daemon appends both of these and can be killed mid-write, so a torn
# record and a half-written last frame are both reachable. Either way the
# answer is a sentence naming the file, not the parser's traceback.
def _record(root: Path, cast_id: str) -> RunRecord | None:
    try:
        return read_record(root, cast_id)
    except (OSError, ValueError) as error:
        msg = f"the record at {run_file(root, cast_id)} cannot be read: {error}"
        raise RitualDefinitionError(msg) from error


def _events(root: Path, cast_id: str) -> list[WireMessage]:
    try:
        return list(read_events(root, cast_id))
    except (OSError, ValueError) as error:
        msg = f"the log at {events_log(root, cast_id)} cannot be read: {error}"
        raise RitualDefinitionError(msg) from error
