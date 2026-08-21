from collections.abc import Callable, Iterator
from typing import assert_never

from vekna.pacts.casts import Casts, CastView, RiteView
from vekna.pacts.routing import Action, Routed, Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastMessage,
    CastStatus,
    CastUpdate,
    DecideRequested,
    DecideResolved,
    GrimoireBegin,
    GrimoireEnd,
    LockAcquireRequested,
    LockDenied,
    LockGranted,
    LockReleased,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    WireMessage,
)

# The two halves of what a cast can say, split so neither branch grows past what
# one screen and pylint's complexity budget hold. The tuple is what the isinstance
# narrowing needs; the alias is what the handler declares. What is *not* one of
# these four falls to `_inside`, so a kind added to the protocol and to no
# handler meets one `assert_never` rather than passing two unreachable ones.
_Inside = RiteStarted | RiteDelta | RiteFinished | DecideRequested | DecideResolved
_About = GrimoireBegin | GrimoireEnd | CastStatus | CastGoodbye
_ABOUT = (GrimoireBegin, GrimoireEnd, CastStatus, CastGoodbye)

_LOCKS_LATER = "locks arrive at 0.7.0"
_NO_CAST = "no such cast"
_NO_RITE = "no such rite"
_NO_PROMPT = "no such prompt"


# A hub with no journal and one with a journal that does nothing behave the
# same, so the default is the second and every use site is one straight line.
def _unrouted(_: Routed) -> None:
    pass


def _unjournalled(_: CastMessage) -> None:
    pass


# The daemon's whole model of what is happening. It holds views, not frames: a
# surface arriving late is sent a replay derived from the view, so a cast that
# has been streaming for an hour costs one screenful to catch up on rather than
# an hour of scrollback.
# ponytail: one hub, no locking — the socket server drives it from a single
# event loop. Per-cast locking is the upgrade if it ever runs threaded.
class Hub(Casts):
    def __init__(
        self,
        *,
        on_routed: Callable[[Routed], None] = _unrouted,
        on_journal: Callable[[CastMessage], None] = _unjournalled,
    ) -> None:
        self._casts: dict[str, CastView] = {}
        self._surfaces: list[Surface] = []
        self._on_routed = on_routed
        self._on_journal = on_journal

    @property
    def casts(self) -> dict[str, CastView]:
        return self._casts

    def attach_surface(self, surface: Surface) -> None:
        self._surfaces.append(surface)
        for message in self._replay():
            surface.send(message)
        self._say(kind="surface_hello", subject=None, action="attached")

    def detach_surface(self, surface: Surface) -> None:
        if surface in self._surfaces:
            self._surfaces.remove(surface)
        self._say(kind="surface_hello", subject=None, action="detached")

    def apply(self, message: CastMessage) -> None:
        if isinstance(message, CastHello):
            self._casts[message.cast_id] = CastView(hello=message)
            self._accept(message)
            return
        if (view := self._casts.get(message.cast_id)) is None:
            self._drop(message, reason=_NO_CAST)
        elif (refused := _update(view, message)) is not None:
            self._drop(message, reason=refused)
        else:
            self._accept(message)

    def _accept(self, message: CastMessage) -> None:
        self._journal(message)
        self._fan_out(message)
        self._say(kind=message.kind, subject=message.cast_id, action="applied")

    # A disk that is full is the daemon's problem and not the cast's. The
    # journal is called from inside a socket read loop, so an OSError let out of
    # here ends that connection and tells the cast it disconnected — over
    # something the cast did nothing about and can do nothing about.
    def _journal(self, message: CastMessage) -> None:
        try:
            self._on_journal(message)
        except OSError as error:
            self._drop(message, reason=f"not journaled: {error}")

    # The same rule one layer over: a viewer that has gone is the daemon's
    # problem, and the cast writing when it went must not be the one that pays.
    # The dead surface is dropped rather than tried again on the next event —
    # its socket is not coming back, and the detach it never got to send is
    # exactly what this stands in for.
    def _fan_out(self, message: CastMessage) -> None:
        for surface in list(self._surfaces):
            try:
                surface.send(message)
            except OSError as error:
                self.detach_surface(surface)
                self._drop(message, reason=f"surface gone: {error}")

    def _drop(self, message: CastMessage, *, reason: str) -> None:
        self._say(
            kind=message.kind, subject=message.cast_id, action="dropped", reason=reason
        )

    def _say(
        self,
        *,
        kind: str,
        subject: str | None,
        action: Action,
        reason: str | None = None,
    ) -> None:
        self._on_routed(
            Routed(kind=kind, subject=subject, action=action, reason=reason)
        )

    # Derived, not recorded: each cast's own `CastHello` opens it, the rites
    # replay in the order they began, and every open prompt is asked again —
    # which is what a surface needs to paint the view the daemon is holding.
    def _replay(self) -> Iterator[WireMessage]:
        for view in self._casts.values():
            yield view.hello
            yield GrimoireBegin(cast_id=view.hello.cast_id)
            yield from _replay_rites(view)
            if view.said is not None:
                yield view.said
            yield from view.waiting.values()
            yield GrimoireEnd(cast_id=view.hello.cast_id)
            yield from _replay_goodbye(view)


# `view`, not `cast`, throughout: the domain word collides with `typing.cast` in
# the repository's own debt metrics, and a view is what these actually hold.
# Returns why the message was refused, or None once it has been applied.
def _update(view: CastView, message: CastUpdate) -> str | None:
    # Answered here rather than by a catch-all under the match: the reason is
    # true of these four and of nothing else, and what is left over is what the
    # matches then have to cover for `assert_never` to hold.
    if isinstance(
        message, (LockAcquireRequested, LockGranted, LockDenied, LockReleased)
    ):
        return _LOCKS_LATER
    if isinstance(message, _ABOUT):
        _about(view, message)
        return None
    return _inside(view, message)


# What happens *inside* a cast: its rites and the prompts they open. Every one
# of these names something that has to exist already, which is why refusing is
# something only this half can do.
def _inside(view: CastView, message: _Inside) -> str | None:
    match message:
        case RiteStarted():
            view.rites[message.rite_id] = RiteView(started=message)
        case RiteDelta() | RiteFinished():
            return _update_rite(view, message)
        case DecideRequested():
            view.waiting[message.request_id] = message
        case DecideResolved():
            return _answer(view, message)
        case _:
            assert_never(message)
    return None


# What the cast says *about itself*: the brackets round a replay, the line it
# says it is working on, and how it ended. Nothing here can be refused — there
# is no earlier message any of them has to match up with, and a `GrimoireEnd`
# has nothing to do, which is why this is a chain and not a match: the fourth
# branch would be a `pass` and a fifth an `assert_never` nothing can reach.
def _about(view: CastView, message: _About) -> None:
    if isinstance(message, GrimoireBegin):
        # The replay rule: what is cached for this cast is what the cast is
        # about to say again, so it goes before the replay rebuilds it.
        view.rites.clear()
        view.waiting.clear()
        view.said = None
    elif isinstance(message, CastStatus):
        # Latest wins, and a cleared one is kept rather than dropped: a surface
        # replayed after a clear has to be told the line is gone.
        view.said = message
    elif isinstance(message, CastGoodbye):
        view.status = message.status
        view.detail = message.detail
        # A cast that is gone is not still asking.
        view.waiting.clear()


def _answer(view: CastView, message: DecideResolved) -> str | None:
    if view.waiting.pop(message.request_id, None) is None:
        return _NO_PROMPT
    return None


def _update_rite(view: CastView, message: RiteDelta | RiteFinished) -> str | None:
    if (rite := view.rites.get(message.rite_id)) is None:
        return _NO_RITE
    if isinstance(message, RiteDelta):
        rite.deltas.extend(message.delta.splitlines() or [""])
    else:
        rite.status = message.status
        rite.finished_at = message.finished_at
    return None


def _replay_rites(view: CastView) -> Iterator[WireMessage]:
    for rite in view.rites.values():
        yield rite.started
        if rite.deltas:
            yield RiteDelta(
                cast_id=view.hello.cast_id,
                rite_id=rite.started.rite_id,
                delta="\n".join(rite.deltas),
            )
        if rite.finished_at is not None and (status := rite.status) != "running":
            yield RiteFinished(
                cast_id=view.hello.cast_id,
                rite_id=rite.started.rite_id,
                status=status,
                finished_at=rite.finished_at,
            )


# A cast that ended before this surface arrived still shows, and shows how it
# ended — `vekna log` lists recent casts, and the daemon has not forgotten
# this one yet.
def _replay_goodbye(view: CastView) -> Iterator[WireMessage]:
    if (status := view.status) != "running":
        yield CastGoodbye(cast_id=view.hello.cast_id, status=status, detail=view.detail)
