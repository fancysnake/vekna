from collections.abc import Callable, Iterator
from typing import assert_never

from typing_extensions import override

from vekna.pacts.casts import CastBoard, CastView, Prompt, RiteView
from vekna.pacts.routing import Action, Routed, Routes, Surface
from vekna.wire import (
    AwaitEnded,
    AwaitRequested,
    AwaitWithdrawn,
    CastGoodbye,
    CastHello,
    CastMessage,
    CastQueued,
    CastRefused,
    CastRequested,
    CastUpdate,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    EnqueueAccepted,
    EnqueueRefused,
    EnqueueRequested,
    GrimoireBegin,
    GrimoireEnd,
    LockAcquireRequested,
    LockDenied,
    LockGranted,
    LockReleased,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    TreeBlocked,
    WireMessage,
)

_LOCKS_LATER = "locks are not built yet"
_NO_CAST = "no such cast"
_NO_RITE = "no such rite"
_NO_PROMPT = "no such prompt"
_NO_PEER = "the cast is not connected"
_SLOTS_ELSEWHERE = "coding slots are the circle's"
_QUEUE_ELSEWHERE = "the queue is the circle's"
_NO_AWAIT = "no such await"
_CLAIMED_ELSEWHERE = "another surface has claimed the prompt"
_ITS_OWN_TERMINAL = "the cast answers it on its own terminal until a surface claims it"
_STARTS_NOTHING = "this daemon starts no casts"
_LOCKS = (LockAcquireRequested, LockGranted, LockDenied, LockReleased)
_SLOTS = (CodingSlotRequested, CodingSlotGranted, CodingSlotReleased)
_ENQUEUES = (EnqueueRequested, EnqueueAccepted, EnqueueRefused)
_ELSEWHERE = (*_LOCKS, *_SLOTS, *_ENQUEUES)
# What a view is made of: every update but the ones above.
_Viewed = (
    CastGoodbye
    | CastQueued
    | GrimoireBegin
    | GrimoireEnd
    | RiteStarted
    | RiteDelta
    | RiteFinished
    | DecideRequested
    | DecideResolved
    | DecideWithdrawn
    | DecideClaimed
    | TreeBlocked
    | AwaitRequested
    | AwaitEnded
    | AwaitWithdrawn
)


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
class Hub(CastBoard, Routes):
    def __init__(
        self,
        *,
        on_routed: Callable[[Routed], None] = _unrouted,
        on_journal: Callable[[CastMessage], None] = _unjournalled,
    ) -> None:
        self._casts: dict[str, CastView] = {}
        self._surfaces: list[Surface] = []
        # The connection each cast is on, which is how the daemon writes back to
        # one: an answer from a surface, a slot.
        self._peers: dict[str, Surface] = {}
        self._on_routed = on_routed
        self._on_journal = on_journal
        # The surface holding each claimed prompt, by request. The view keeps
        # the claim id every surface is told; only the daemon knows the holder.
        self._claims: dict[str, tuple[str, Surface]] = {}

    @property
    def casts(self) -> dict[str, CastView]:
        return self._casts

    def attach_surface(self, surface: Surface) -> None:
        self._surfaces.append(surface)
        for message in self._replay():
            surface.send(message)
        self._say(kind="surface_hello", cast_id=None, action="attached")

    # A claim dies with the surface that made it, or the prompt would wait on a
    # window nobody has open: the answerer it took over takes it back.
    def detach_surface(self, surface: Surface) -> None:
        if surface in self._surfaces:
            self._surfaces.remove(surface)
        self._say(kind="surface_hello", cast_id=None, action="detached")
        self._prune()
        for request_id, (cast_id, holder) in list(self._claims.items()):
            if holder is surface:
                del self._claims[request_id]
                self._claimed(
                    DecideClaimed(cast_id=cast_id, request_id=request_id, claim_id=None)
                )

    def open_cast(self, cast_id: str, peer: Surface) -> None:
        self._peers[cast_id] = peer

    # A cast that reattached has a newer peer by the time its old connection
    # goes, and that one is the one to keep.
    def close_cast(self, cast_id: str, peer: Surface) -> None:
        if self._peers.get(cast_id) is peer:
            del self._peers[cast_id]

    # Whether it reached the cast. A peer whose socket has gone is dropped the
    # same way a surface is.
    def tell(self, cast_id: str, message: WireMessage) -> bool:
        if (peer := self._peers.get(cast_id)) is None:
            return False
        try:
            peer.send(message)
        except OSError:
            del self._peers[cast_id]
            return False
        return True

    @override
    def request(self, surface: Surface, request: CastRequested) -> None:
        del request
        surface.send(CastRefused(reason=_STARTS_NOTHING))

    # Forwarded, not applied: the cast's own `DecideResolved` is what closes the
    # prompt, so the journal and every surface hear one answer, from the cast
    # that took it. A prompt that is not open — answered already, withdrawn,
    # never asked — goes nowhere, and neither does one from a surface the
    # prompt is not that surface's to answer.
    def answer(self, surface: Surface, resolved: DecideResolved) -> None:
        view = self._casts.get(resolved.cast_id)
        if view is None or resolved.request_id not in view.waiting:
            self._drop(resolved, reason=_NO_PROMPT)
        elif (refused := self._not_theirs(view, surface, resolved)) is not None:
            self._drop(resolved, reason=refused)
        elif not self.tell(resolved.cast_id, resolved):
            self._drop(resolved, reason=_NO_PEER)
        else:
            self._say(kind=resolved.kind, cast_id=resolved.cast_id, action="applied")

    # Told to every surface and to the cast, so whoever was answering it stops.
    def claim(self, surface: Surface, claimed: DecideClaimed) -> None:
        view = self._casts.get(claimed.cast_id)
        if view is None or claimed.request_id not in view.waiting:
            self._drop(claimed, reason=_NO_PROMPT)
        elif claimed.claim_id is None:
            self._drop(claimed, reason="a surface lets go of a claim by leaving")
        else:
            self._prune()
            self._claims[claimed.request_id] = (claimed.cast_id, surface)
            self._claimed(claimed)

    # A claim outlives its prompt here until something looks: the prompt
    # closing is the cast's message, and carries no word of who held it.
    def _prune(self) -> None:
        self._claims = {
            request_id: held
            for request_id, held in self._claims.items()
            if (view := self._casts.get(held[0])) is not None
            and (prompt := view.waiting.get(request_id)) is not None
            and prompt.claim_id is not None
        }

    def _claimed(self, claimed: DecideClaimed) -> None:
        self.apply(claimed)
        self.tell(claimed.cast_id, claimed)

    def _not_theirs(
        self, view: CastView, surface: Surface, resolved: DecideResolved
    ) -> str | None:
        if view.waiting[resolved.request_id].claim_id is not None:
            held = self._claims.get(resolved.request_id)
            mine = held is not None and held[1] is surface
            return None if mine else _CLAIMED_ELSEWHERE
        return None if view.hello.wired else _ITS_OWN_TERMINAL

    def apply(self, message: CastMessage) -> None:
        if isinstance(message, CastHello):
            self._casts[message.cast_id] = CastView(hello=message)
            self._accept(message)
            return
        if (view := self._casts.get(message.cast_id)) is None:
            self._drop(message, reason=_NO_CAST)
        elif (refused := _refusal(view, message)) is not None:
            self._drop(message, reason=refused)
        else:
            self._accept(message)

    def _accept(self, message: CastMessage) -> None:
        self._journal(message)
        self._fan_out(message)
        self._say(kind=message.kind, cast_id=message.cast_id, action="applied")

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
            kind=message.kind, cast_id=message.cast_id, action="dropped", reason=reason
        )

    def _say(
        self,
        *,
        kind: str,
        cast_id: str | None,
        action: Action,
        reason: str | None = None,
    ) -> None:
        self._on_routed(
            Routed(kind=kind, cast_id=cast_id, action=action, reason=reason)
        )

    # Derived, not recorded: each cast's own `CastHello` opens it, the rites
    # replay in the order they began, and every open prompt is asked again —
    # which is what a surface needs to paint the view the daemon is holding.
    def _replay(self) -> Iterator[WireMessage]:
        for view in self._casts.values():
            yield view.hello
            yield GrimoireBegin(cast_id=view.hello.cast_id)
            yield from _replay_rites(view)
            yield from _replay_prompts(view)
            yield from view.on_children.values()
            yield GrimoireEnd(cast_id=view.hello.cast_id)
            if view.status == "queued":
                yield CastQueued(cast_id=view.hello.cast_id)
            yield from _replay_goodbye(view)
            if view.blocked is not None:
                yield view.blocked


# `view`, not `cast`, throughout: the domain word collides with `typing.cast` in
# the repository's own debt metrics, and a view is what these actually hold.
# Returns why the message was refused, or None once it has been applied.
# Answered here rather than by a catch-all under the match: the reasons are true
# of these seven and of nothing else, and what is left over is what the match
# then has to cover for `assert_never` to hold.
def _refusal(view: CastView, message: CastUpdate) -> str | None:
    if isinstance(message, _ELSEWHERE):
        return _elsewhere(message)
    return _update(view, message)


def _update(view: CastView, message: _Viewed) -> str | None:
    refused: str | None = None
    match message:
        case GrimoireBegin():
            # The replay rule: what is cached for this cast is what the cast is
            # about to say again, so it goes before the replay rebuilds it.
            view.rites.clear()
            view.waiting.clear()
            view.on_children.clear()
        case GrimoireEnd():
            pass
        case CastQueued():
            view.status = "queued"
        case RiteStarted():
            view.rites[message.rite_id] = RiteView(started=message)
        case RiteDelta() | RiteFinished():
            refused = _update_rite(view, message)
        case (
            DecideRequested()
            | DecideResolved()
            | DecideWithdrawn()
            | DecideClaimed()
            | AwaitRequested()
            | AwaitEnded()
            | AwaitWithdrawn()
        ):
            refused = _update_wait(view, message)
        case CastGoodbye():
            view.status = message.status
            view.detail = message.detail
            # A cast that is gone is not still asking, nor awaiting.
            view.waiting.clear()
            view.on_children.clear()
        case TreeBlocked():
            # Said after the cast is gone, and nothing else about it changes.
            view.blocked = message
        case _:
            assert_never(message)
    return refused


def _elsewhere(
    message: (
        LockAcquireRequested
        | LockGranted
        | LockDenied
        | LockReleased
        | CodingSlotRequested
        | CodingSlotGranted
        | CodingSlotReleased
        | EnqueueRequested
        | EnqueueAccepted
        | EnqueueRefused
    ),
) -> str:
    if isinstance(message, _SLOTS):
        return _SLOTS_ELSEWHERE
    if isinstance(message, _ENQUEUES):
        return _QUEUE_ELSEWHERE
    return _LOCKS_LATER


# What a cast is blocked on: a human's answer, or another cast.
def _update_wait(
    view: CastView,
    message: (
        DecideRequested
        | DecideResolved
        | DecideWithdrawn
        | DecideClaimed
        | AwaitRequested
        | AwaitEnded
        | AwaitWithdrawn
    ),
) -> str | None:
    match message:
        case DecideRequested():
            view.waiting[message.request_id] = Prompt(request=message)
        case AwaitRequested():
            view.on_children[message.request_id] = message
        case DecideResolved() | DecideWithdrawn():
            if view.waiting.pop(message.request_id, None) is None:
                return _NO_PROMPT
        case DecideClaimed():
            return _claim(view, message)
        case _:
            if view.on_children.pop(message.request_id, None) is None:
                return _NO_AWAIT
    return None


def _update_rite(view: CastView, message: RiteDelta | RiteFinished) -> str | None:
    if (rite := view.rites.get(message.rite_id)) is None:
        return _NO_RITE
    if isinstance(message, RiteDelta):
        rite.deltas.extend(message.delta.splitlines() or [""])
    else:
        rite.finished = message
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
        if rite.finished is not None:
            yield rite.finished


# A cast that ended before this surface arrived still shows, and shows how it
# ended — `vekna log` lists recent casts, and the daemon has not forgotten
# this one yet.
def _replay_goodbye(view: CastView) -> Iterator[WireMessage]:
    match view.status:
        case "ok" | "error" | "disconnected" as status:
            yield CastGoodbye(
                cast_id=view.hello.cast_id, status=status, detail=view.detail
            )


def _claim(view: CastView, message: DecideClaimed) -> str | None:
    if (prompt := view.waiting.get(message.request_id)) is None:
        return _NO_PROMPT
    prompt.claim_id = message.claim_id
    return None


# A claim is said after the prompt it claims, so a late surface knows what is
# being answered before it hears who holds it.
def _replay_prompts(view: CastView) -> Iterator[WireMessage]:
    for prompt in view.waiting.values():
        yield prompt.request
        if prompt.claim_id is not None:
            yield DecideClaimed(
                cast_id=view.hello.cast_id,
                request_id=prompt.request.request_id,
                claim_id=prompt.claim_id,
            )
