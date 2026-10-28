import shlex
from collections.abc import Callable

from vekna.wire import (
    CastRequested,
    DecideRequested,
    DecideResolved,
    HeldTree,
    ParkedTree,
    PurifiedTree,
    WireMessage,
    allowed_answers,
    parse_flags,
)

_CAST_USAGE = "c <ritual> [--flag value ...]"


# What `c <ritual> --flag v` typed into either view does, and what the view says
# after. The flags read the way `vekna cast` reads them, and what they mean is
# the ritual's to say: the cast the daemon spawns validates them, and a bad one
# shows as that cast failing.
def request_cast(*, typed: str, root: str, send: Callable[[WireMessage], None]) -> str:
    try:
        ritual, *flags = shlex.split(typed)
        request = CastRequested(
            project_root=root, ritual=ritual, components=parse_flags(flags)
        )
    except ValueError as error:
        return f"{_CAST_USAGE} — {error}"
    send(request)
    return f"asked for {request.ritual}"


# What `vekna purify` says about one tree.
def purified(tree: PurifiedTree) -> str:
    match tree:
        case HeldTree():
            return f"{tree.path}: held by a running cast, left alone"
        case ParkedTree():
            said = "purified"
        case _:
            said = f"failed: {tree.reason}"
    saved = f" — its uncommitted work is on {tree.saved}" if tree.saved else ""
    return f"{tree.path}: {said}{saved}"


# The answer typed to `request`, checked by the rule the cast checks it by, so
# a typo is said at once rather than ignored there. What the view says when it
# is refused; nothing once it has been sent.
def send_answer(
    *, request: DecideRequested, typed: str, send: Callable[[WireMessage], None]
) -> str | None:
    allowed = allowed_answers(options=request.options, free=request.free)
    if allowed is not None and typed not in allowed:
        return f"{typed!r} is not one of {', '.join(allowed)}"
    send(
        DecideResolved(
            cast_id=request.cast_id, request_id=request.request_id, answer=typed
        )
    )
    return None
