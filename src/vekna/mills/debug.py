from vekna.pacts.routing import Routed

# `--debug` is read after the fact, next to a cast that misbehaved, so a line
# says which cast or lich before it says what happened: the eye scans the column
# it is filtering on.
_NO_SUBJECT = "-"


def debug_line(routed: Routed) -> str:
    parts = [routed.subject or _NO_SUBJECT, routed.kind, routed.action]
    if routed.reason is not None:
        parts.append(f"({routed.reason})")
    return " ".join(parts)
