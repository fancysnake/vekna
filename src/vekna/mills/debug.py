from vekna.pacts.routing import Routed

# `--debug` is read after the fact, next to a cast that misbehaved, so a line
# says which cast before it says what happened: the eye scans the column it is
# filtering on.
_NO_CAST = "-"


def debug_line(routed: Routed) -> str:
    parts = [routed.cast_id or _NO_CAST, routed.kind, routed.action]
    if routed.reason is not None:
        parts.append(f"({routed.reason})")
    return " ".join(parts)
