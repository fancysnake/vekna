import asyncio
import logging
from datetime import UTC, datetime

import pytest

from vekna.mills.relay import Relay
from vekna.pacts.casts import Casts, CastView, Prompt
from vekna.pacts.remote import Hear, Heard, Posted, Remote, RemoteError
from vekna.wire import (
    CastHello,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    DecideWithdrawn,
    RiteDelta,
    WireMessage,
)

_NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_OPERATOR = 7
_STRANGER = 8
_CAST = "c0ffee00" + "0" * 24
_THREAD = "pr_fix fix/login c0ffee00"
_LONGEST_NAME = 100


class _Board(Casts):
    def __init__(self) -> None:
        self._casts: dict[str, CastView] = {}

    @property
    def casts(self) -> dict[str, CastView]:
        return self._casts

    def seen(self, hello: CastHello) -> None:
        self._casts[hello.cast_id] = CastView(hello=hello)

    def asks(self, request: DecideRequested, *, claim_id: str | None = None) -> None:
        self._casts[request.cast_id].waiting[request.request_id] = Prompt(
            request, claim_id
        )


# Threads are numbered as they are first asked in, and messages as posted.
class _Chat(Remote):
    def __init__(self) -> None:
        self.asked: list[tuple[str, str, str]] = []
        self.said: list[tuple[str, str]] = []
        self.failing = False

    async def ask(self, *, room: str, thread: str, text: str) -> Posted:
        if self.failing:
            msg = "Discord is down"
            raise RemoteError(msg)
        self.asked.append((room, thread, text))
        names = list(dict.fromkeys(name for _, name, _ in self.asked))
        return Posted(
            thread=f"t{names.index(thread) + 1}", message=f"m{len(self.asked)}"
        )

    async def say(self, *, thread: str, text: str) -> None:
        self.said.append((thread, text))

    async def run(self, hear: Hear) -> None:
        raise NotImplementedError


class _Desk:
    def __init__(self) -> None:
        self.board = _Board()
        self.chat = _Chat()
        self.answers: list[tuple[object, DecideResolved]] = []
        self.branch: str | None = "fix/login"
        self.looked: list[str] = []
        self.relay = Relay(
            casts=self.board,
            answer=lambda surface, resolved: self.answers.append((surface, resolved)),
            remote=self.chat,
            allow=frozenset({_OPERATOR}),
            branch=self._branch_of,
        )

    async def _branch_of(self, path: str) -> str | None:
        self.looked.append(path)
        return self.branch

    # The relay runs until its queue is empty: nothing in it or in the chat
    # waits on anything else.
    async def told(self, *messages: WireMessage) -> None:
        for message in messages:
            if isinstance(message, DecideRequested):
                self.board.asks(message)
            self.relay.send(message)
        running = asyncio.create_task(self.relay.run())
        await asyncio.sleep(0)
        if running.done():
            running.result()
        running.cancel()

    async def hears(
        self,
        text: str,
        *,
        author: int = _OPERATOR,
        thread: str = "t1",
        reply_to: str | None = None,
    ) -> str | None:
        return await self.relay.heard(
            Heard(author=author, thread=thread, reply_to=reply_to, text=text)
        )

    def answered(self) -> list[tuple[str, str]]:
        assert all(surface is self.relay for surface, _ in self.answers)
        return [(resolved.request_id, resolved.answer) for _, resolved in self.answers]


def _hello(
    cast_id: str = _CAST,
    *,
    vigil: str | None = "prwatch",
    enqueued_by: str | None = None,
    wired: bool = True,
) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/app",
        project="/app/.git",
        ritual="pr_fix",
        components={"pull_request": 74},
        started_at=_NOW,
        wired=wired,
        vigil=vigil,
        enqueued_by=enqueued_by,
    )


def _push(request_id: str = "r1", *, cast_id: str = _CAST) -> DecideRequested:
    return DecideRequested(
        cast_id=cast_id,
        request_id=request_id,
        prompt="push the fix to #74?",
        options=["push", "decline"],
    )


def _question(
    *, options: list[str] | None = None, free: bool = False
) -> DecideRequested:
    return DecideRequested(
        cast_id=_CAST, request_id="r1", prompt="which?", options=options, free=free
    )


@pytest.fixture(name="desk")
def _desk() -> _Desk:
    desk = _Desk()
    desk.board.seen(_hello())
    return desk


@pytest.mark.asyncio
class TestAsking:
    @staticmethod
    async def test_a_vigil_casts_question_goes_to_its_thread_in_its_projects_room(
        desk: _Desk,
    ):
        await desk.told(_push())

        assert desk.chat.asked == [
            (
                "app",
                _THREAD,
                (
                    "**pr_fix** asks:\npush the fix to #74?\n1. push\n2. decline\n"
                    "reply with a number"
                ),
            )
        ]
        assert not desk.chat.said
        assert desk.looked == ["/app"]

    @staticmethod
    async def test_a_cast_keeps_the_thread_it_first_asked_in_when_its_branch_changes(
        desk: _Desk,
    ):
        desk.branch = None
        await desk.told(_push())
        desk.branch = "fix/other"

        await desk.told(_push("r2"))

        assert [thread for _, thread, _ in desk.chat.asked] == ["pr_fix c0ffee00"] * 2
        assert desk.looked == ["/app"]

    @staticmethod
    @pytest.mark.parametrize(
        ("request_", "ending"),
        [
            (_question(), "which?\nreply yes or no"),
            (_question(free=True), "which?"),
            (
                _question(options=["a", "b"], free=True),
                "which?\n1. a\n2. b\nreply with a number, or in your own words",
            ),
        ],
    )
    async def test_the_question_says_how_it_is_answered(
        desk: _Desk, request_: DecideRequested, ending: str
    ):
        await desk.told(request_)

        [(_, _, text)] = desk.chat.asked
        assert text == f"**pr_fix** asks:\n{ending}"

    @staticmethod
    async def test_a_thread_name_keeps_the_casts_id_however_long_the_branch(
        desk: _Desk,
    ):
        desk.branch = "x" * 200

        await desk.told(_push())

        [(_, thread, _)] = desk.chat.asked
        assert len(thread) == _LONGEST_NAME
        assert thread.startswith("pr_fix xxx")
        assert thread.endswith("x c0ffee00")

    @staticmethod
    async def test_a_cast_enqueued_under_a_vigils_cast_is_asked_for_too(desk: _Desk):
        desk.board.seen(_hello("child", vigil=None, enqueued_by=_CAST))
        desk.board.seen(_hello("grandchild", vigil=None, enqueued_by="child"))

        await desk.told(_push(cast_id="grandchild"))

        [(room, thread, _)] = desk.chat.asked
        assert (room, thread) == ("app", "pr_fix fix/login grandchi")

    @staticmethod
    async def test_a_cast_whose_ancestor_is_forgotten_is_asked_for(desk: _Desk):
        desk.board.seen(_hello("orphan", vigil=None, enqueued_by="gone"))

        await desk.told(_push(cast_id="orphan"))

        assert len(desk.chat.asked) == 1

    @staticmethod
    @pytest.mark.parametrize("enqueued_by", [None, "typed"])
    async def test_a_cast_typed_by_hand_and_what_it_enqueued_are_not_asked_for(
        desk: _Desk, enqueued_by: str | None
    ):
        desk.board.seen(_hello("typed", vigil=None, wired=False))
        desk.board.seen(_hello("other", vigil=None, enqueued_by=enqueued_by))

        await desk.told(_push(cast_id="other"))

        assert not desk.chat.asked

    @staticmethod
    async def test_a_question_told_twice_is_posted_once(desk: _Desk):
        await desk.told(_push(), _push())

        assert len(desk.chat.asked) == 1

    @staticmethod
    async def test_a_question_of_a_cast_nobody_knows_and_other_messages_are_passed_over(
        desk: _Desk,
    ):
        desk.relay.send(_push(cast_id="unknown"))
        await desk.told(
            RiteDelta(cast_id=_CAST, rite_id="r", delta="x"),
            DecideClaimed(cast_id=_CAST, request_id="r1", claim_id="w"),
        )

        assert not desk.chat.asked
        assert not desk.chat.said

    @staticmethod
    async def test_the_answer_the_cast_took_is_said_in_the_thread(desk: _Desk):
        await desk.told(
            _push(), DecideResolved(cast_id=_CAST, request_id="r1", answer="push")
        )

        assert desk.chat.said == [("t1", "→ push")]

    @staticmethod
    async def test_a_withdrawn_question_is_said_and_one_never_posted_is_not(
        desk: _Desk,
    ):
        await desk.told(
            _push(),
            DecideWithdrawn(cast_id=_CAST, request_id="r1"),
            DecideWithdrawn(cast_id=_CAST, request_id="r1"),
            DecideResolved(cast_id=_CAST, request_id="never", answer="push"),
        )

        assert desk.chat.said == [("t1", "withdrawn")]

    @staticmethod
    async def test_a_question_posted_is_logged(
        desk: _Desk, caplog: pytest.LogCaptureFixture
    ):
        with caplog.at_level(logging.INFO, logger="vekna.mills.relay"):
            await desk.told(_push())

        assert [record.getMessage() for record in caplog.records] == [
            f"asked the remote r1 for cast {_CAST}"
        ]

    @staticmethod
    async def test_a_post_that_fails_is_logged_and_the_next_question_is_posted(
        desk: _Desk, caplog: pytest.LogCaptureFixture
    ):
        desk.chat.failing = True
        await desk.told(_push())
        desk.chat.failing = False

        await desk.told(_push("r2"))

        assert [text.splitlines()[1] for _, _, text in desk.chat.asked] == [
            "push the fix to #74?"
        ]
        assert [
            record.getMessage()
            for record in caplog.records
            if record.levelno == logging.WARNING
        ] == [
            (
                f"could not tell the remote of decide_requested in cast {_CAST}:"
                " Discord is down"
            )
        ]


@pytest.mark.asyncio
class TestHearing:
    @staticmethod
    @pytest.mark.parametrize(
        ("typed", "answer"),
        [
            ("push", "push"),
            ("2", "decline"),
            (" Push ", "push"),
            ("DECLINE", "decline"),
        ],
    )
    async def test_an_option_is_answered_by_its_name_or_number_whatever_the_case(
        desk: _Desk, typed: str, answer: str
    ):
        await desk.told(_push())

        assert await desk.hears(typed) is None
        assert desk.answered() == [("r1", answer)]

    @staticmethod
    @pytest.mark.parametrize(
        ("typed", "answer"), [("Yes", "yes"), ("n", "no"), ("Y", "yes"), ("2", "no")]
    )
    async def test_a_bare_question_takes_yes_and_no_as_a_phone_types_them(
        desk: _Desk, typed: str, answer: str
    ):
        await desk.told(_question())

        assert await desk.hears(typed) is None
        assert desk.answered() == [("r1", answer)]

    @staticmethod
    @pytest.mark.parametrize(
        ("options", "typed", "answer"),
        [
            (None, "Yes, but rebase first", "Yes, but rebase first"),
            (None, "y", "y"),
            (["a", "b"], "2", "b"),
            (["a", "b"], "neither: c", "neither: c"),
            ([], "1", "1"),
        ],
    )
    async def test_a_free_question_takes_anything_and_a_number_still_picks(
        desk: _Desk, options: list[str] | None, typed: str, answer: str
    ):
        await desk.told(_question(options=options, free=True))

        assert await desk.hears(typed) is None
        assert desk.answered() == [("r1", answer)]

    @staticmethod
    async def test_an_answer_outside_the_options_is_refused_by_name(desk: _Desk):
        await desk.told(_push())

        assert await desk.hears("merge") == "'merge' is not one of push, decline"
        assert await desk.hears("3") == "'3' is not one of push, decline"
        assert await desk.hears("  ") == "an empty reply answers nothing"
        assert not desk.answered()

    @staticmethod
    async def test_an_author_not_allowed_and_a_thread_of_no_cast_get_no_word(
        desk: _Desk,
    ):
        await desk.told(_push())

        assert await desk.hears("push", author=_STRANGER) is None
        assert await desk.hears("push", thread="t9") is None
        assert not desk.answered()

    @staticmethod
    async def test_a_question_a_window_claimed_is_left_to_the_window(desk: _Desk):
        await desk.told(_push())
        desk.board.asks(_push(), claim_id="window")

        assert await desk.hears("push") == (
            "a window has taken this question over: answer it there"
        )
        assert not desk.answered()

    @staticmethod
    async def test_a_reply_with_no_question_open_says_so(desk: _Desk):
        await desk.told(
            _push(), DecideResolved(cast_id=_CAST, request_id="r1", answer="push")
        )
        said = await desk.hears("push")
        await desk.told(_push("r2"))
        desk.board.casts[_CAST].waiting.clear()

        assert said == "no question is open in this cast"
        assert await desk.hears("push") == "no question is open in this cast"
        assert not desk.answered()

    @staticmethod
    async def test_a_reply_in_the_thread_of_a_cast_the_daemon_forgot_says_so(
        desk: _Desk,
    ):
        await desk.told(_push())
        del desk.board.casts[_CAST]

        assert await desk.hears("push") == "no question is open in this cast"
        assert not desk.answered()

    @staticmethod
    async def test_a_reply_answers_the_oldest_question_unless_it_replies_to_one(
        desk: _Desk,
    ):
        desk.board.seen(_hello("other"))
        await desk.told(_push(), _push("r2"), _push("r3", cast_id="other"))

        assert await desk.hears("push") is None
        assert await desk.hears("decline", reply_to="m2") is None
        assert await desk.hears("1", reply_to="m3") is None
        assert await desk.hears("2", thread="t2") is None
        assert desk.answered() == [
            ("r1", "push"),
            ("r2", "decline"),
            ("r1", "push"),
            ("r3", "decline"),
        ]
