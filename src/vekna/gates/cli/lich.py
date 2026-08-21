from collections.abc import Sequence
from datetime import UTC, datetime

from vekna.pacts.lich import LichLine

_NAME = 16
_STATE = 18
_NONE = "no liches — `vekna lich` raises one here\n"
_NEW = "a new one"
_MINUTE = 60
_HOUR = 3600
_DAY = 86400


# "3 days ago" over a timestamp: what the prompt is asking is which of these you
# were working in, and nobody holds the wall clock of three days ago in their
# head. Coarse on purpose — an hour's precision decides nothing here.
def _ago(when: datetime, now: datetime) -> str:
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < _MINUTE:
        return "just now"
    if seconds < _HOUR:
        return f"{seconds // _MINUTE}m ago"
    if seconds < _DAY:
        return f"{seconds // _HOUR}h ago"
    days = seconds // _DAY
    return "yesterday" if days == 1 else f"{days}d ago"


# What the lich last did, which is the only thing that tells two dormant rows in
# one directory apart. The row holds the cast id and the journal holds the rest,
# so a lich that cast something the daemon never saw says so rather than lying.
def _last(line: LichLine, now: datetime) -> str:
    if line.row.last_cast is None:
        return "cast nothing yet"
    if (record := line.last) is None:
        return f"last cast {line.row.last_cast[:8]}"
    return f"last cast {record.hello.ritual}, {_ago(record.hello.started_at, now)}"


def _state(line: LichLine) -> str:
    if not line.live:
        return "dormant"
    if (said := line.said) is None or said.ritual is None:
        return "idle"
    return f"casting {said.ritual}"


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


# `vekna liches`: every lich this account has, live or dormant, and where each
# stands. Rows come off the registry and liveness off the daemon — a lich is
# live because a socket says so, which is why nothing on disk claims it.
def listing(lines: Sequence[LichLine], *, now: datetime | None = None) -> str:
    if not lines:
        return _NONE
    at = _now(now)
    return "".join(
        f"{line.row.name:<{_NAME}}  {_state(line):<{_STATE}}"
        f"  {line.row.root}  {_last(line, at)}\n"
        for line in lines
    )


# Where something already sleeps, `vekna lich` cannot know which one is meant,
# and guessing is wrong in both directions: silently reviving a lich you had
# finished with is no better than silently abandoning one you meant to carry on.
# So it asks, and says what each last did — which is what tells them apart.
def raising_prompt(lines: Sequence[LichLine], *, now: datetime | None = None) -> str:
    at = _now(now)
    count = (
        "One lich sleeps here."
        if len(lines) == 1
        else f"{len(lines)} liches sleep here."
    )
    numbered = [
        f"  [{index}] {line.row.name:<{_NAME}}  {_last(line, at)}"
        for index, line in enumerate(lines, start=1)
    ]
    return "\n".join([count, *numbered, f"  [n] {_NEW}", ""])
