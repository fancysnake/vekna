import asyncio
import contextlib
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from datetime import UTC
from pathlib import Path

from pydantic import ValidationError

from ._pacts import (
    AdmissionRequested,
    CastGoodbye,
    CastMessage,
    CastRefused,
    CastSeen,
    DaemonVersion,
    RunRecord,
    VersionRequested,
    VigilsRequested,
    VigilsState,
    WireMessage,
    decode_frame,
    encode_frame,
)
from ._refusals import explained
from ._specs import VERSION, compatible, major

_EVENTS = "events.jsonl"
_RUN = "run.json"
_RUNS_ENV = "VEKNA_RUNS"
_SOCKET_ENV = "VEKNA_SOCKET"
_RUNTIME_ENV = "XDG_RUNTIME_DIR"
_STATE_ENV = "XDG_STATE_HOME"
_OWN_STATE_ENV = "VEKNA_STATE"
_PRIVATE = 0o700
_OPEN_TO_OTHERS = 0o077
_PROBE_SECONDS = 2.0
_PREDATES_SEEN = (
    "this daemon predates marking a cast seen: `vekna stop` ends it, and the"
    " next `vekna` starts one that marks"
)
_UNSAID = "does not say its version, so it predates this check"
# One frame is one line, and a rite's result is a field of it: a shell medium
# hands back everything the command printed, so `git diff` against a branch is a
# single frame of megabytes. asyncio's stream default is 64KiB, and a frame over
# it is a `ValueError` — read as an unreadable frame, which ends the connection.
# Every end that reads frames opens its stream with this, or the one that does
# not is the one that hangs up on what the others carried.
# ponytail: a ceiling, not a fix. A result bigger than this still ends the
# connection; framing the length ahead of the payload is the upgrade.
FRAME_LIMIT = 32 * 1024 * 1024


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
# `VEKNA_STATE` is read first: a second daemon beside the first needs a journal
# and a worktree pool of its own, and `XDG_STATE_HOME` would move every other
# program's state with them.
def default_state_root() -> Path:
    if (own := os.environ.get(_OWN_STATE_ENV)) is not None:
        return Path(own)
    if (named := os.environ.get(_STATE_ENV)) is not None:
        return Path(named) / "vekna"
    return Path.home() / ".local" / "state" / "vekna"


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


# The daemon's one reply to `question` on a fresh connection, or `None` for one
# that hangs up, garbles or says nothing in time. Nobody listening is the
# `OSError` the connect raised. Bounded both ways, because a wedged daemon would
# otherwise hang every `vekna` on its probe.
async def _asked(path: Path, question: WireMessage) -> WireMessage | None:
    async with asyncio.timeout(_PROBE_SECONDS):
        reader, writer = await asyncio.open_unix_connection(
            str(path), limit=FRAME_LIMIT
        )
    try:
        writer.write(encode_frame(question))
        with contextlib.suppress(OSError, ValueError):
            async with asyncio.timeout(_PROBE_SECONDS):
                return await anext(read_frames(reader), None)
        return None
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()


# The version of the daemon listening on `path`, or `None` for one that does not
# say: a daemon that predates the question.
async def daemon_version(path: Path) -> str | None:
    reply = await _asked(path, VersionRequested())
    return reply.version if isinstance(reply, DaemonVersion) else None


# Why this vekna will not talk to the daemon on `path`, and the two ways out, or
# `None` when it will. A second daemon needs a state directory as well as a
# socket: two daemons on one journal and one worktree pool each take the
# other's casts and trees for their own.
def refused(path: Path, theirs: str | None) -> str | None:
    if compatible(theirs):
        return None
    said = _UNSAID if theirs is None else f"is vekna {theirs}"
    state = default_state_root()
    beside = (
        f"VEKNA_SOCKET={path.with_name(f'vekna-{major(VERSION)}.sock')}"
        f" VEKNA_STATE={state.with_name(f'{state.name}-{major(VERSION)}')}"
    )
    return (
        f"the daemon on {path} {said}, and this is vekna {VERSION}: a daemon"
        " serves its own major version only.\n"
        "`vekna stop` ends it, and the next `vekna` starts this version's.\n"
        f"To run this version beside it, export for every vekna that uses it:\n"
        f"  {beside}"
    )


# `refused` for whatever listens on `path` now, and `None` when nothing does.
async def daemon_refusal(path: Path) -> str | None:
    try:
        theirs = await daemon_version(path)
    except OSError:
        return None
    return refused(path, theirs)


# Why the daemon on `path` has no room for one more cast typed in
# `project_root`, or `None` when the cast may run: admitted, nobody listening,
# or a daemon that hangs up on a question it predates.
async def admission_refusal(path: Path, project_root: str) -> str | None:
    try:
        reply = await _asked(path, AdmissionRequested(project_root=project_root))
    except OSError:
        return None
    return reply.reason if isinstance(reply, CastRefused) else None


# Why the daemon on `path` did not take the mark, or `None` when it did. Asked
# on a connection of its own: a daemon that predates `CastSeen` hangs up on the
# frame, and on the window's connection that ends the window.
async def mark_seen(path: Path, mark: CastSeen) -> str | None:
    try:
        reply = await _asked(path, mark)
    except OSError as error:
        return f"the daemon did not take the mark: {error}"
    if isinstance(reply, CastRefused):
        return reply.reason
    return None if isinstance(reply, CastGoodbye) else _PREDATES_SEEN


# Whether the daemon on `path` has its vigils paused. `None` when the daemon
# did not say: nobody listening, or a daemon that hangs up on a question it
# predates.
async def vigils_paused(path: Path) -> bool | None:
    return await _vigils_state(path, VigilsRequested())


# Pauses the vigils of the daemon on `path`, or lets them cast again, and
# answers as `vigils_paused` does.
async def set_vigils_paused(path: Path, *, paused: bool) -> bool | None:
    return await _vigils_state(path, VigilsRequested(pause=paused))


# Asked on a connection of its own for the reason `mark_seen` is.
async def _vigils_state(path: Path, asked: VigilsRequested) -> bool | None:
    try:
        reply = await _asked(path, asked)
    except OSError:
        return None
    return reply.paused if isinstance(reply, VigilsState) else None


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
    try:
        record = RunRecord.model_validate_json(path.read_text())
    except ValidationError as error:
        raise ValueError(explained(error)) from error
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
