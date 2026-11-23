import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from typing_extensions import override

from vekna.pacts.casts import Casts, named
from vekna.pacts.remote import Heard, Posted, Remote, RemoteError
from vekna.pacts.routing import Surface
from vekna.wire import (
    SHORT_ID,
    CastHello,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    WireMessage,
    allowed_answers,
    picked_option,
)

_log = logging.getLogger(__name__)

# The remote's longest thread name.
_THREAD_NAME = 100
_BRIEF = {"y": "yes", "n": "no"}
_YES_NO = tuple(_BRIEF.values())
_NOTHING_OPEN = "no question is open in this cast"
_CLAIMED = "a window has taken this question over: answer it there"
_EMPTY = "an empty reply answers nothing"


@dataclass(frozen=True, kw_only=True)
class _Asked:
    request: DecideRequested
    posted: Posted


# A cast's thread: its name, what the remote calls it, and the questions open
# in it by request, oldest first.
@dataclass(kw_only=True)
class _Thread:
    name: str
    at: str
    asked: dict[str, _Asked] = field(default_factory=dict)


# A surface with no screen: the questions of casts a vigil started go to a
# remote, each in its cast's thread of its project's room, and what an allowed
# author writes there is the answer. It claims nothing, so a window answers
# the same prompts, and whichever answer the cast takes is said in the thread.
# shortcut: what was posted is remembered in memory, so a restarted daemon
# posts every open question again; a file of what was posted is the upgrade.
class Relay(Surface):
    def __init__(
        self,
        *,
        casts: Casts,
        answer: Callable[[Surface, DecideResolved], None],
        remote: Remote,
        allow: frozenset[int],
        branch: Callable[[str], Awaitable[str | None]],
    ) -> None:
        self._casts = casts
        self._answer = answer
        self._remote = remote
        self._allow = allow
        self._branch = branch
        self._told: asyncio.Queue[
            DecideRequested | DecideResolved | DecideWithdrawn
        ] = asyncio.Queue()
        self._threads: dict[str, _Thread] = {}

    @override
    def send(self, message: WireMessage) -> None:
        if isinstance(message, (DecideRequested, DecideResolved, DecideWithdrawn)):
            self._told.put_nowait(message)

    # One message at a time, so a question is posted before its answer is said.
    # A remote that fails loses that one post: the prompt stays open for a
    # window to answer.
    async def run(self) -> None:
        for _ in itertools.count():
            message = await self._told.get()
            try:
                await self._relayed(message)
            except RemoteError as error:
                _log.warning(
                    "could not tell the remote of %s in cast %s: %s",
                    message.kind,
                    message.cast_id,
                    error,
                )

    async def _relayed(
        self, message: DecideRequested | DecideResolved | DecideWithdrawn
    ) -> None:
        if isinstance(message, DecideRequested):
            await self._ask(message)
        elif (
            thread := self._threads.get(message.cast_id)
        ) is not None and thread.asked.pop(message.request_id, None) is not None:
            said = (
                f"→ {message.answer}"
                if isinstance(message, DecideResolved)
                else "withdrawn"
            )
            await self._remote.say(thread=thread.at, text=said)

    async def _ask(self, request: DecideRequested) -> None:
        view = self._casts.casts.get(request.cast_id)
        thread = self._threads.get(request.cast_id)
        if (
            view is None
            or (thread is not None and request.request_id in thread.asked)
            or not self._kept(view.hello)
        ):
            return
        name = (
            _thread(view.hello, branch=await self._branch(view.hello.project_root))
            if thread is None
            else thread.name
        )
        posted = await self._remote.ask(
            room=named(view.hello.project),
            thread=name,
            text=_worded(view.hello, request),
        )
        self._threads.setdefault(
            request.cast_id, _Thread(name=name, at=posted.thread)
        ).asked[request.request_id] = _Asked(request=request, posted=posted)
        _log.info(
            "asked the remote %s for cast %s", request.request_id, request.cast_id
        )

    # A cast a vigil started, or one enqueued under it: nobody sits at a
    # terminal for those. An ancestor the daemon no longer knows counts as a
    # vigil's, because a question asked twice costs less than a cast that waits
    # on nobody.
    def _kept(self, hello: CastHello) -> bool:
        if hello.vigil is not None or hello.enqueued_by is None:
            return hello.vigil is not None
        parent = self._casts.casts.get(hello.enqueued_by)
        return parent is None or self._kept(parent.hello)

    # What is said back to the author. `None` for an author who is not allowed
    # and for a thread that is no cast's: neither is told anything is here.
    async def heard(self, reply: Heard) -> str | None:
        found = next(
            (
                (cast_id, thread)
                for cast_id, thread in self._threads.items()
                if thread.at == reply.thread
            ),
            None,
        )
        if reply.author not in self._allow or found is None:
            return None
        cast_id, thread = found
        # The question replied to, or the oldest one open in the thread.
        open_ = list(thread.asked.values())
        replied = [asked for asked in open_ if asked.posted.message == reply.reply_to]
        if (asked := next(iter(replied or open_), None)) is None:
            return _NOTHING_OPEN
        view = self._casts.casts.get(cast_id)
        prompt = None if view is None else view.waiting.get(asked.request.request_id)
        if prompt is None:
            return _NOTHING_OPEN
        if prompt.claim_id is not None:
            return _CLAIMED
        return self._answered(asked.request, typed=reply.text.strip())

    # Checked by the rule the cast checks it by, so a typo is said in the
    # thread rather than ignored there.
    def _answered(self, request: DecideRequested, *, typed: str) -> str | None:
        if not typed:
            return _EMPTY
        answer = _read(typed, request)
        allowed = allowed_answers(options=request.options, free=request.free)
        if allowed is not None and answer not in allowed:
            return f"{typed!r} is not one of {', '.join(allowed)}"
        self._answer(
            self,
            DecideResolved(
                cast_id=request.cast_id, request_id=request.request_id, answer=answer
            ),
        )
        return None


# A phone capitalises the first word, so an option is matched whatever its
# case, and a number names the option at that place in the menu.
def _read(typed: str, request: DecideRequested) -> str:
    if request.options is None:
        if request.free:
            return typed
        typed = _BRIEF.get(typed.casefold(), typed)
    offered = _YES_NO if request.options is None else tuple(request.options)
    if (chosen := picked_option(typed, offered)) is not None:
        return chosen
    return next(
        (option for option in offered if option.casefold() == typed.casefold()), typed
    )


# Named once, at the cast's first question: a cast switches the branch under
# its own feet, and a second name would be a second thread. The cast's short id
# ends the name, and a thread is found again by its name.
def _thread(hello: CastHello, *, branch: str | None) -> str:
    ending = f" {hello.cast_id[:SHORT_ID]}"
    title = hello.ritual if branch is None else f"{hello.ritual} {branch}"
    return title[: _THREAD_NAME - len(ending)] + ending


def _worded(hello: CastHello, request: DecideRequested) -> str:
    lines = [f"**{hello.ritual}** asks:", request.prompt]
    if request.options:
        lines += [f"{at}. {option}" for at, option in enumerate(request.options, 1)]
        lines.append(
            "reply with a number, or in your own words"
            if request.free
            else "reply with a number"
        )
    elif not request.free:
        lines.append("reply yes or no")
    return "\n".join(lines)
