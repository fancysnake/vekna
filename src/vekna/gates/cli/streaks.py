import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import JsonValue

from vekna.pacts.casts import CastView

from .cast_text import live

Kids = Mapping[str, Sequence[CastView]]


def _started(view: CastView) -> tuple[datetime, str]:
    return view.hello.started_at, view.hello.cast_id


def _dumped(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def said_args(view: CastView) -> str:
    return _dumped(view.hello.components)


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


# How a cast ended, with how each cast it queued ended, by ritual and
# arguments. A failure is told apart by what it said.
@dataclass(frozen=True)
class _Outcome:
    status: str
    result: JsonValue | None
    detail: str | None
    queued: tuple[tuple[str, str, "_Outcome"], ...]


# None while the cast or one it queued still runs.
def _outcome(view: CastView, kids: Kids) -> _Outcome | None:
    if live(view):
        return None
    queued: list[tuple[str, str, _Outcome]] = []
    for kid in kids.get(view.hello.cast_id, ()):
        if (ended := _outcome(kid, kids)) is None:
            return None
        queued.append((kid.hello.ritual, said_args(kid), ended))
    detail = None if view.status == "ok" else view.ending.detail
    return _Outcome(view.status, view.ending.result, detail, tuple(queued))


# The casts of one ritual with one set of arguments, cut where a cast ended
# differently from the one before it: newest streak first, and in a streak the
# newest cast first. A cast still running is a streak of its own.
def streaks(views: Sequence[CastView], kids: Kids) -> list[tuple[CastView, ...]]:
    found: list[list[CastView]] = []
    last: _Outcome | None = None
    for view in sorted(views, key=_started):
        outcome = _outcome(view, kids)
        if found and outcome is not None and outcome == last:
            found[-1].append(view)
        else:
            found.append([view])
        last = outcome
    return [tuple(reversed(streak)) for streak in reversed(found)]


# For each cast, the arguments that tell it from the others, as it was typed:
# an argument every one of them shares says nothing. A queued cast does not
# know its arguments yet, so it is left out of the comparison.
def flags_apart(views: Sequence[CastView]) -> dict[str, str]:
    known = [view.hello.components for view in views if view.status != "queued"]
    names = sorted({name for components in known for name in components})
    apart = [name for name in names if len({_dumped(c.get(name)) for c in known}) > 1]
    return {
        view.hello.cast_id: " ".join(
            f"--{name} {view.hello.components[name]}"
            for name in apart
            if name in view.hello.components
        )
        for view in views
    }
