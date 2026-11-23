import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from typing_extensions import override

from vekna.pacts.casts import Casts, ancestry, named
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
_NOTHING_OPEN = "no question is open in this thread"
_CLOSED = "that question is closed: reply to an open one"
_CLAIMED = "a window has taken this question over: answer it there"
_EMPTY = "an empty reply answers nothing"
_UNMATCHED = "more than one question is open: reply to the question itself"


# A question, where it was posted, and whether it was answered or withdrawn.
@dataclass(kw_only=True)
class _Asked:
    request: DecideRequested
    posted: Posted
    closed: bool = False


# A question is told apart by its cast and its request.
_Question = tuple[str, str]


def _question(message: DecideRequested | DecideResolved | DecideWithdrawn) -> _Question:
    return message.cast_id, message.request_id


# A surface with no screen: the questions of casts a vigil started go to a
# remote, each in its cast's thread of its project's room, and what is written
# there is the answer. It claims nothing, so a window answers the same prompts,
# and whichever answer the cast takes is said in the thread.
# shortcut: what was posted is remembered in memory, so a restarted daemon
# posts every open question again; a file of what was posted is the upgrade.
class Relay(Surface):
    def __init__(
        self,
        *,
        casts: Casts,
        answer: Callable[[Surface, DecideResolved], None],
        remote: Remote,
        branch: Callable[[str], Awaitable[str | None]],
    ) -> None:
        self._casts = casts
        self._answer = answer
        self._remote = remote
        self._branch = branch
        self._told: asyncio.Queue[
            DecideRequested | DecideResolved | DecideWithdrawn
        ] = asyncio.Queue()
        # Every question posted, oldest first. A cast has more than one thread
        # when the remote archived the first, so each question has its own.
        self._asked: dict[_Question, _Asked] = {}
        self._names: dict[str, str] = {}

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
        elif (asked := self._asked.get(_question(message))) is not None and (
            not asked.closed
        ):
            asked.closed = True
            said = (
                f"→ {message.answer}"
                if isinstance(message, DecideResolved)
                else "withdrawn"
            )
            await self._remote.say(thread=asked.posted.thread, text=said)

    async def _ask(self, request: DecideRequested) -> None:
        view = self._casts.casts.get(request.cast_id)
        if (
            view is None
            or _question(request) in self._asked
            or not self._kept(view.hello)
        ):
            return
        if (name := self._names.get(request.cast_id)) is None:
            name = _thread(
                view.hello, branch=await self._branch(view.hello.project_root)
            )
        posted = await self._remote.ask(
            room=named(view.hello.project),
            thread=name,
            text=_worded(view.hello, request),
        )
        self._names[request.cast_id] = name
        self._asked[_question(request)] = _Asked(request=request, posted=posted)
        _log.info(
            "asked the remote %s for cast %s", request.request_id, request.cast_id
        )

    # A cast a vigil started, or one enqueued under it: nobody sits at a
    # terminal for those. An ancestor the daemon no longer knows, or a chain
    # that loops, counts as a vigil's, because a question asked twice costs less
    # than a cast that waits on nobody.
    def _kept(self, hello: CastHello) -> bool:
        for each in ancestry(self._casts, hello):
            if each.vigil is not None:
                return True
            if each.enqueued_by is None:
                return False
        return True

    # What is said back to the writer, or `None` for a thread that is no cast's.
    async def heard(self, reply: Heard) -> str | None:
        here = [
            asked
            for asked in self._asked.values()
            if asked.posted.thread == reply.thread
        ]
        if not here:
            return None
        asked = _addressed(here, reply)
        if isinstance(asked, str):
            return asked
        request = asked.request
        view = self._casts.casts.get(request.cast_id)
        prompt = None if view is None else view.waiting.get(request.request_id)
        if prompt is None:
            return _NOTHING_OPEN
        if prompt.claim_id is not None:
            return _CLAIMED
        return self._answered(request, typed=reply.text.strip())

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


# The question replied to, or the oldest one open in the thread, or what is said
# back when the reply names no question and more than one is open.
def _addressed(here: list[_Asked], reply: Heard) -> _Asked | str:
    replied = [asked for asked in here if asked.posted.message == reply.reply_to]
    if any(asked.closed for asked in replied):
        return _CLOSED
    open_ = [asked for asked in here if not asked.closed]
    if reply.reply_to is not None and not replied and len(open_) > 1:
        return _UNMATCHED
    return next(iter(replied or open_), _NOTHING_OPEN)


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
