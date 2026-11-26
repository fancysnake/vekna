import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
_NOTHING_OPEN = "no question is open in this thread"
_CLOSED = "that question is closed: reply to an open one"
_CLAIMED = "a window has taken this question over: answer it there"
_EMPTY = "an empty reply answers nothing"
_UNMATCHED = "more than one question is open: reply to the question itself"
_WORDS_ONLY = "this question takes no reaction: reply in words"
_YES_NO_REACTIONS = {"👍": "yes", "❌": "no"}
# One for each of the first ten options: a menu longer than that is answered
# past them by its numbers.
_NUMBER_REACTIONS = (
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
)
# A remote may hand an emoji back without its variation selector, and a hand
# that picked it from the keyboard may have a skin tone on it.
_DECORATION = str.maketrans(
    "", "", "\ufe0f\U0001f3fb\U0001f3fc\U0001f3fd\U0001f3fe\U0001f3ff"
)


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


# A surface with no screen: the questions of casts the daemon spawned go to a
# remote, each in its cast's thread of its project's room, and what is written
# there is the answer. It claims nothing, so a window answers the same prompts,
# and whichever answer the cast takes is said in the thread.
# shortcut: what was posted is remembered in memory, so a restarted daemon
# asks every open question again, and the remote posts again each one that no
# longer stands last in its thread; a file of what was posted is the upgrade.
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
        # Every question posted, oldest first. A thread holds the questions of
        # every cast of its ritual on its branch, and a cast has a second
        # thread when the remote archived the first, so each question has its
        # own.
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
            said = "✅ ACK" if isinstance(message, DecideResolved) else "🚫 withdrawn"
            await self._remote.say(thread=asked.posted.thread, text=said)

    async def _ask(self, request: DecideRequested) -> None:
        view = self._casts.casts.get(request.cast_id)
        if (
            view is None
            or _question(request) in self._asked
            # A cast typed at a terminal asks there. What it enqueued is asked
            # for here as well as there: the terminal may be gone by now, and a
            # question asked twice costs less than a cast that waits on nobody.
            or not view.hello.wired
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
            reactions=tuple(_reactions(request)),
        )
        self._names[request.cast_id] = name
        self._asked[_question(request)] = _Asked(request=request, posted=posted)
        _log.info(
            "asked the remote %s for cast %s", request.request_id, request.cast_id
        )
        # The first of them the question takes answers it; one it refuses is
        # told why, as a reply written now would be.
        for typed in posted.unheard:
            reply = Heard(thread=posted.thread, reply_to=posted.message, text=typed)
            if (said := await self.heard(reply)) is None:
                return
            await self._remote.say(thread=posted.thread, text=said)

    # What is said back to the writer, or `None` for a thread that is no cast's.
    async def heard(self, reply: Heard) -> str | None:
        here = [
            asked
            for asked in self._asked.values()
            if asked.posted.thread == reply.thread
        ]
        # A reaction answers the question it is on, and under any other
        # message it is no answer at all.
        if not here or (
            reply.reaction
            and all(asked.posted.message != reply.reply_to for asked in here)
        ):
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
        if reply.reaction:
            return self._reacted(request, emoji=reply.text)
        return self._answered(request, typed=reply.text.strip())

    def _reacted(self, request: DecideRequested, *, emoji: str) -> str | None:
        if not (offered := _reactions(request)):
            return _WORDS_ONLY
        meant = {_plain(known): answer for known, answer in offered.items()}
        if (answer := meant.get(_plain(emoji))) is None:
            return f"{emoji} is not one of {' '.join(offered)}"
        return self._answered(request, typed=answer)

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


# The emoji that answer a question, each with the answer it gives, in the order
# they are put under it: the one the ritual named for the answer, else the
# thumb or the number. A question that takes only words has none.
def _reactions(request: DecideRequested) -> dict[str, str]:
    chosen = request.reactions or {}
    if request.options is None:
        if request.free:
            return {}
        return {
            chosen.get(answer, emoji): answer
            for emoji, answer in _YES_NO_REACTIONS.items()
        }
    emoji = dict(zip(request.options, _NUMBER_REACTIONS, strict=False)) | chosen
    return {emoji[option]: option for option in request.options if option in emoji}


def _plain(emoji: str) -> str:
    return emoji.translate(_DECORATION)


# Named after the ritual and the branch, so every cast of one ritual on one
# branch asks in one thread and the thread is found again by its name. Named
# once, at the cast's first question: a cast switches the branch under its own
# feet, and a second name would be a second thread.
def _thread(hello: CastHello, *, branch: str | None) -> str:
    title = hello.ritual if branch is None else f"{hello.ritual} {branch}"
    return title[:_THREAD_NAME]


def _worded(hello: CastHello, request: DecideRequested) -> str:
    asking = f"**{hello.ritual}** `{hello.cast_id[:SHORT_ID]}`"
    lines = [f"❓ {asking} asks", request.prompt]
    chosen = request.reactions or {}
    if request.options:
        lines += [
            (
                f"{at}. {chosen[option]} {option}"
                if option in chosen
                else f"{at}. {option}"
            )
            for at, option in enumerate(request.options, 1)
        ]
        how = "reply with a number"
        how += ", or in your own words" if request.free else ""
    elif request.free:
        how = "reply in your own words"
    else:
        how = "reply yes or no"
        if chosen:
            said = (f"{emoji} {to}" for emoji, to in _reactions(request).items())
            how += f": {', '.join(said)}"
    return "\n".join([*lines, f"💬 _{how}_"])
