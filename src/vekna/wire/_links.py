import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC
from pathlib import Path

from pydantic import ValidationError

from ._pacts import CastMessage, RunRecord, WireMessage, decode_frame
from ._refusals import explained

_EVENTS = "events.jsonl"
_RUN = "run.json"
_RUNS_ENV = "VEKNA_RUNS"
_SOCKET_ENV = "VEKNA_SOCKET"
_RUNTIME_ENV = "XDG_RUNTIME_DIR"
_STATE_ENV = "XDG_STATE_HOME"
_CONFIG_ENV = "XDG_CONFIG_HOME"
_PROJECT_CONFIG = ".vekna.toml"
_PRIVATE = 0o700
_OPEN_TO_OTHERS = 0o077


async def read_frames(reader: asyncio.StreamReader) -> AsyncIterator[WireMessage]:
    async for raw in reader:
        if stripped := raw.strip():
            yield decode_frame(stripped)


# What a connection carries once its first frame has said what it is. An opening
# frame this late opens nothing, so it is dropped here once rather than by every
# reader in turn.
async def cast_frames(frames: AsyncIterator[WireMessage]) -> AsyncIterator[CastMessage]:
    async for message in frames:
        if isinstance(message, CastMessage):
            yield message


# Where the socket and the journal are, and how to read back what the daemon
# wrote there. Here rather than beside either end, because both ends need it and
# `vekna.wire` is all they share: a cast process may not import the daemon's
# layers, and two copies of these drift silently — a resume looking in the wrong
# directory reports that the daemon never saw the cast.
# `VEKNA_RUNS` is read first, which is what lets a test — or a second user on
# one machine — keep their own.
def default_runs_root() -> Path:
    if (named := os.environ.get(_RUNS_ENV)) is not None:
        return Path(named)
    return default_state_root() / "runs"


# What the daemon writes down rather than what the user configured: a journal of
# what ran and a debug log of what it did with each event. XDG calls that state
# — history and what survives a restart — and puts it under `~/.local/state`,
# which is a different directory from `~/.config` on purpose. Both of vekna's
# are here, so moving the namespace moves them together.
def default_state_root() -> Path:
    if (named := os.environ.get(_STATE_ENV)) is not None:
        return Path(named) / "vekna"
    return Path.home() / ".local" / "state" / "vekna"


# What the user configured, which is the one thing of vekna's that belongs in
# the config namespace — the journal and the debug log are state and live under
# `default_state_root()`. Here because the cast reads `[rituals]` from it and
# the daemon reads `[circle]`.
def default_config_path() -> Path:
    if (named := os.environ.get(_CONFIG_ENV)) is not None:
        return Path(named) / "vekna" / "config.toml"
    return Path.home() / ".config" / "vekna" / "config.toml"


# The project's own config, nearest first, as both ends find it.
def project_config_path(directory: Path) -> Path | None:
    for here in (directory, *directory.parents):
        if (found := here / _PROJECT_CONFIG).is_file():
            return found
    return None


# Inside a directory of this user's own, which is why this makes one. A socket
# is created with the process umask and can only be chmod'ed afterwards, so a
# socket sitting directly in `/tmp` is connectable by anybody for as long as
# that takes — long enough to read every cast on the account, and the path is
# guessable enough to sit and wait for. A directory carries its permissions
# before the socket exists, and it also stops somebody else getting there first
# and leaving a socket of their own for a cast to talk into.
# `XDG_RUNTIME_DIR` is already that directory where the session provides one.
def default_socket_path() -> Path:
    if (named := os.environ.get(_SOCKET_ENV)) is not None:
        return Path(named)
    if (runtime := os.environ.get(_RUNTIME_ENV)) is not None:
        return Path(runtime) / "vekna.sock"
    return _owned(Path(tempfile.gettempdir()) / f"vekna-{os.getuid()}") / "vekna.sock"


# What a cast groups under and what a surface filters by, so both ends resolve
# it here. Git's common dir is one per repository whatever tree asks. A
# directory git will not place in a repository — or a machine without git — is
# its own project.
async def project_of(directory: Path) -> str:
    here = await asyncio.to_thread(directory.resolve)
    try:
        git = await asyncio.create_subprocess_exec(
            "git",
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            cwd=here,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return str(here)
    answer, _ = await git.communicate()
    return answer.decode().strip() if git.returncode == 0 else str(here)


def _owned(directory: Path) -> Path:
    directory.mkdir(mode=_PRIVATE, exist_ok=True)
    seen = directory.stat()
    if seen.st_uid != os.getuid() or seen.st_mode & _OPEN_TO_OTHERS:
        msg = (
            f"{directory} is not this user's alone — vekna will not put a socket in it"
        )
        raise PermissionError(msg)
    return directory


def run_file(root: Path, cast_id: str) -> Path:
    return root / cast_id / _RUN


def events_log(root: Path, cast_id: str) -> Path:
    return root / cast_id / _EVENTS


# No record is None: a cast that ran with no daemon listening leaves none. A
# record that will not parse is the caller's to answer for — the listing shows
# it as damaged, a resume says which file it was.
# A `started_at` need not carry a zone: the field is a plain `datetime`, so a
# `run.json` written by hand or by something that is not this daemon can land
# without one. Read as UTC, the zone this daemon's own writer records in, so
# every reader — the journal's sort, `vekna log`'s local time — agrees. The
# alternative, calling such a record damaged, has `prune` deleting a run that
# resumes perfectly well.
def read_record(root: Path, cast_id: str) -> RunRecord | None:
    path = run_file(root, cast_id)
    if not path.is_file():
        return None
    record = RunRecord.model_validate_json(path.read_text())
    if record.hello.started_at.tzinfo is None:
        record.hello.started_at = record.hello.started_at.replace(tzinfo=UTC)
    return record


def read_events(root: Path, cast_id: str) -> Iterator[WireMessage]:
    path = events_log(root, cast_id)
    if not path.is_file():
        return
    with path.open("rb") as events:
        for line, frame in enumerate(events, start=1):
            if not frame.strip():
                continue
            # A log runs to thousands of frames, and the parser's report names
            # the field but not the frame it was in.
            try:
                message = decode_frame(frame)
            except ValidationError as error:
                msg = f"line {line}: {explained(error)}"
                raise ValueError(msg) from error
            yield message
