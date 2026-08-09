from datetime import UTC, datetime
from pathlib import Path


# Never the rendered view: the daemon paints over its terminal, so a debug line
# printed there would be gone before it could be read. The path is echoed once
# at startup, and the file is appended to for the life of the daemon.
class DebugLog:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, line: str) -> None:
        stamp = datetime.now(tz=UTC).isoformat(timespec="milliseconds")
        with self._path.open("a", encoding="utf-8") as log:
            log.write(f"{stamp} {line}\n")
