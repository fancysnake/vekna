from pathlib import Path

from vekna.lexicon._pacts import Resumption, RitualDefinitionError
from vekna.wire import default_runs_root, read_events, read_record, run_file


# A cast with no journal is a cast that ran with no daemon listening, and the
# answer to "resume it" is that there is nothing to resume from — said as a
# sentence naming the directory that is not there.
def read_run(cast_id: str, *, root: Path | None = None) -> Resumption:
    where = root if root is not None else default_runs_root()
    if (record := read_record(where, cast_id)) is None:
        run = run_file(where, cast_id)
        msg = (
            f"no journal for cast {cast_id!r} at {run.parent}"
            " — only a cast the daemon saw can be resumed"
        )
        raise RitualDefinitionError(msg)
    return Resumption(record=record, events=list(read_events(where, cast_id)))
