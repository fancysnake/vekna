import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from vekna.pacts.casts import CastView

from .cast_text import ago, live

Kids = Mapping[str, Sequence[CastView]]


def _started(view: CastView) -> tuple[datetime, str]:
    return view.hello.started_at, view.hello.cast_id


def said_args(view: CastView) -> str:
    return json.dumps(view.hello.components, sort_keys=True, default=str)


# The casts each cast queued, oldest first, of the ones in hand: a cast whose
# parent is not among them hangs under no cast.
def kids_of(casts: Sequence[CastView]) -> dict[str, list[CastView]]:
    known = {view.hello.cast_id for view in casts}
    kids: dict[str, list[CastView]] = {}
    for view in sorted(casts, key=_started):
        parent = view.hello.enqueued_by
        if parent in known and parent != view.hello.cast_id:
            kids.setdefault(parent or "", []).append(view)
    return kids


def with_kids(views: Sequence[CastView], kids: Kids) -> list[CastView]:
    found: list[CastView] = []
    for view in views:
        found += [view, *with_kids(kids.get(view.hello.cast_id, ()), kids)]
    return found


# How a cast ended: its status, and the other statuses the casts under it
# ended with, so a cast that queued none ended like one whose casts all ended
# as it did. What the cast said is not part of it, so casts that said different
# things still stand for each other; the right page shows the newest of them.
# None while the cast or one it queued still runs.
def _outcome(view: CastView, kids: Kids) -> tuple[str, frozenset[str]] | None:
    if live(view):
        return None
    under: set[str] = set()
    for kid in kids.get(view.hello.cast_id, ()):
        if (ended := _outcome(kid, kids)) is None:
            return None
        under |= {ended[0], *ended[1]}
    return view.status, frozenset(under - {view.status})


# The casts of one ritual with one set of arguments, cut where a cast ended
# differently from the one before it, and where it began in another slot of `ago`:
# newest streak first, and in a streak the newest cast first, whose time the
# line of the streak says. A cast still running is a streak of
# its own.
def streaks(
    views: Sequence[CastView], kids: Kids, *, now: datetime
) -> list[tuple[CastView, ...]]:
    found: list[list[CastView]] = []
    last: tuple[tuple[str, frozenset[str]], str] | None = None
    for view in sorted(views, key=_started):
        outcome = _outcome(view, kids)
        ended = None if outcome is None else (outcome, ago(view, now))
        if found and ended is not None and ended == last:
            found[-1].append(view)
        else:
            found.append([view])
        last = ended
    return [tuple(reversed(streak)) for streak in reversed(found)]
