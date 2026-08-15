import sys
from datetime import UTC, datetime
from pathlib import Path


# Never the rendered view: the daemon paints over its terminal, so a debug line
# printed there would be gone before it could be read. The path is echoed once
# at startup, and the file is appended to for the life of the daemon.
class DebugLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._broken = False
        path.parent.mkdir(parents=True, exist_ok=True)

    # The one failure with nowhere good to be reported: this is the reporting
    # channel, and the daemon writes it from the path every event takes. A log
    # that cannot be written must not be able to end the cast being logged — but
    # silence would leave an operator reading a file that stopped growing with
    # no way to tell that from a quiet daemon. So: said once, to stderr, and
    # never again, because the next event would say the same thing.
    def write(self, line: str) -> None:
        stamp = datetime.now(tz=UTC).isoformat(timespec="milliseconds")
        try:
            with self._path.open("a", encoding="utf-8") as log:
                log.write(f"{stamp} {line}\n")
        except OSError as error:
            self._give_up(error)

    def _give_up(self, error: OSError) -> None:
        if not self._broken:
            self._broken = True
            sys.stderr.write(f"vekna: {self._path} cannot be written: {error}\n")
