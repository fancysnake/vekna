import asyncio
import io
import warnings
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.lexicon._links.follow import Follower
from vekna.lexicon._mills.follow import Lineage
from vekna.lexicon._pacts import StandalonePromptError
from vekna.links.socket_server import serve
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed, Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    CastQueued,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
    GrimoireBegin,
    GrimoireEnd,
    RiteDelta,
    RiteFinished,
    RiteStarted,
    WireMessage,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 200
_TICK = 0.01


def _hello(cast_id: str, *, by: str | None, ritual: str = "ci_watch") -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        project="/proj/.git",
        ritual=ritual,
        components={},
        started_at=_WHEN,
        wired=True,
        enqueued_by=by,
    )


def _asked(cast_id: str = "child0000") -> DecideRequested:
    return DecideRequested(
        cast_id=cast_id, request_id="q1", prompt="push?", options=["yes", "no"]
    )


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s"
    raise AssertionError(msg)


class _Peer(Surface):
    def __init__(self) -> None:
        self.sent: list[WireMessage] = []

    def send(self, message: WireMessage) -> None:
        self.sent.append(message)


class _Asker:
    def __init__(self, answer: str = "yes") -> None:
        self.answer = answer
        self.asked: list[str] = []
        self.cancelled = 0
        self.released = asyncio.Event()

    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        del options, free
        self.asked.append(prompt)
        try:
            await self.released.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return self.answer


class _Refuser:
    @staticmethod
    async def decide(
        *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        del prompt, options, free
        msg = "no terminal to ask on"
        raise StandalonePromptError(msg)


def _rite(cast_id: str = "child0000") -> tuple[RiteStarted, RiteDelta, RiteFinished]:
    return (
        RiteStarted(
            cast_id=cast_id,
            rite_id="r1",
            parent_id=None,
            name="watch",
            category="step",
            started_at=_WHEN,
        ),
        RiteDelta(cast_id=cast_id, rite_id="r1", delta="checks red"),
        RiteFinished(cast_id=cast_id, rite_id="r1", status="ok", finished_at=_WHEN),
    )


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path) -> Path:
    return tmp_path / "vekna.sock"


@pytest.mark.asyncio
class TestFollowing:
    @staticmethod
    async def test_it_prints_its_casts_under_their_names_and_settles_when_they_end(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        lineage = Lineage("root")
        lineage.expect("child0000")
        out = io.StringIO()
        follower = Follower(socket_path=socket_path, lineage=lineage, out=out, ask=None)
        await follower.attach()
        hub.apply(_hello("stranger", by=None, ritual="other"))
        hub.apply(_hello("child0000", by="root"))
        hub.apply(
            RiteStarted(
                cast_id="child0000",
                rite_id="r1",
                parent_id=None,
                name="watch",
                category="step",
                started_at=_WHEN,
            )
        )
        hub.apply(RiteDelta(cast_id="child0000", rite_id="r1", delta="checks red"))
        hub.apply(
            RiteFinished(
                cast_id="child0000", rite_id="r1", status="ok", finished_at=_WHEN
            )
        )
        hub.apply(CastGoodbye(cast_id="stranger", status="error"))
        hub.apply(CastGoodbye(cast_id="child0000", status="ok"))

        assert await asyncio.wait_for(follower.until_settled(), timeout=2)
        assert out.getvalue().splitlines() == [
            "[ci_watch child000] ▶ watch",
            "[ci_watch child000]   checks red",
            "[ci_watch child000] ✓ watch",
            "[ci_watch child000] ✓ done",
        ]
        await follower.close()
        await server.close()

    @staticmethod
    async def test_a_cast_saying_itself_again_shows_nothing_twice(socket_path: Path):
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        server = await serve(path=socket_path, routes=hub)
        lineage = Lineage("root")
        lineage.expect("child0000")
        out = io.StringIO()
        follower = Follower(socket_path=socket_path, lineage=lineage, out=out, ask=None)
        await follower.attach()
        await _eventually(lambda: any(r.action == "attached" for r in routed))
        hub.apply(_hello("child0000", by="root"))
        for message in _rite():
            hub.apply(message)

        hub.apply(_hello("child0000", by="root"))
        hub.apply(GrimoireBegin(cast_id="child0000"))
        for message in _rite():
            hub.apply(message)
        hub.apply(GrimoireEnd(cast_id="child0000"))
        hub.apply(CastQueued(cast_id="child0000"))
        hub.apply(CastGoodbye(cast_id="child0000", status="ok"))

        assert await asyncio.wait_for(follower.until_settled(), timeout=2)
        assert out.getvalue().splitlines() == [
            "[ci_watch child000] ▶ watch",
            "[ci_watch child000]   checks red",
            "[ci_watch child000] ✓ watch",
            "[ci_watch child000] ✓ done",
        ]
        await follower.close()
        await server.close()

    @staticmethod
    async def test_a_cast_heard_before_its_parent_is_not_shown(socket_path: Path):
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        server = await serve(path=socket_path, routes=hub)
        lineage = Lineage("root")
        lineage.expect("child0000")
        out = io.StringIO()
        asker = _Asker()
        follower = Follower(
            socket_path=socket_path, lineage=lineage, out=out, ask=asker
        )
        await follower.attach()
        await _eventually(lambda: any(r.action == "attached" for r in routed))
        started, delta, finished = _rite("grand0000")
        hub.apply(_hello("grand0000", by="child0000"))
        hub.apply(started)
        hub.apply(_asked("grand0000"))

        hub.apply(_hello("child0000", by="root"))
        hub.apply(delta)
        hub.apply(finished)
        hub.claim(
            _Peer(), DecideClaimed(cast_id="grand0000", request_id="q1", claim_id="k1")
        )
        hub.apply(GrimoireBegin(cast_id="grand0000"))
        hub.apply(GrimoireEnd(cast_id="grand0000"))
        hub.apply(CastGoodbye(cast_id="grand0000", status="ok"))
        hub.apply(CastGoodbye(cast_id="child0000", status="ok"))

        assert await asyncio.wait_for(follower.until_settled(), timeout=2)
        assert out.getvalue() == "[ci_watch child000] ✓ done\n"
        assert not asker.asked
        await follower.close()
        await server.close()

    @staticmethod
    async def test_the_daemon_going_ends_the_follow_unsettled(socket_path: Path):
        routed: list[Routed] = []
        server = await serve(path=socket_path, routes=Hub(on_routed=routed.append))
        lineage = Lineage("root")
        lineage.expect("child0000")
        follower = Follower(
            socket_path=socket_path, lineage=lineage, out=io.StringIO(), ask=None
        )
        await follower.attach()
        await _eventually(lambda: any(r.action == "attached" for r in routed))

        await server.close()

        assert not await asyncio.wait_for(follower.until_settled(), timeout=2)
        await follower.close()

    @staticmethod
    async def test_the_daemon_hanging_up_closes_the_connection_here(socket_path: Path):
        hung_up = asyncio.Event()

        async def daemon(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            writer.write_eof()
            await reader.read()
            hung_up.set()
            writer.close()

        server = await asyncio.start_unix_server(daemon, path=str(socket_path))
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=None,
        )
        with warnings.catch_warnings(record=True) as warned:
            warnings.simplefilter("always")
            await follower.attach()

            await asyncio.wait_for(hung_up.wait(), timeout=2)

        assert not [w for w in warned if issubclass(w.category, ResourceWarning)]
        server.close()
        await follower.close()

    @staticmethod
    async def test_with_no_daemon_there_is_nothing_to_follow(socket_path: Path):
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=None,
        )

        assert not await follower.attach()
        await follower.close()


@pytest.mark.asyncio
class TestPrompts:
    @staticmethod
    async def test_it_asks_its_casts_prompts_here_and_the_answer_reaches_them(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        asker = _Asker(answer="yes")
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=asker,
        )
        await follower.attach()
        peer = _Peer()
        hub.open_cast("child0000", peer)
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())
        await _eventually(lambda: bool(asker.asked))

        asker.released.set()
        await _eventually(lambda: bool(peer.sent))

        assert asker.asked == ["[ci_watch child000] push?"]
        assert peer.sent == [
            DecideResolved(cast_id="child0000", request_id="q1", answer="yes")
        ]
        await follower.close()
        await server.close()

    @staticmethod
    async def test_a_claim_takes_the_prompt_away_and_letting_go_hands_it_back(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        asker = _Asker()
        out = io.StringIO()
        follower = Follower(
            socket_path=socket_path, lineage=Lineage("root"), out=out, ask=asker
        )
        await follower.attach()
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())
        await _eventually(lambda: bool(asker.asked))
        window = _Peer()

        hub.claim(
            window, DecideClaimed(cast_id="child0000", request_id="q1", claim_id="k1")
        )
        await _eventually(lambda: asker.cancelled == 1)
        hub.detach_surface(window)
        await _eventually(lambda: asker.asked == ["[ci_watch child000] push?"] * 2)

        assert "[ci_watch child000] taken over in `vekna`: push?" in out.getvalue()
        await follower.close()
        await server.close()

    @staticmethod
    async def test_unattended_it_says_where_to_answer_and_asks_nothing(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        out = io.StringIO()
        follower = Follower(
            socket_path=socket_path, lineage=Lineage("root"), out=out, ask=None
        )
        await follower.attach()
        hub.apply(_hello("child0000", by="root"))

        hub.apply(_asked())
        await _eventually(lambda: "push?" in out.getvalue())

        assert out.getvalue() == (
            "[ci_watch child000] ⏸ push? — answer it in `vekna`\n"
        )
        await follower.close()
        await server.close()

    @staticmethod
    async def test_unattended_a_prompt_answered_elsewhere_says_nothing_more(
        socket_path: Path,
    ):
        routed: list[Routed] = []
        hub = Hub(on_routed=routed.append)
        server = await serve(path=socket_path, routes=hub)
        lineage = Lineage("root")
        lineage.expect("child0000")
        out = io.StringIO()
        follower = Follower(socket_path=socket_path, lineage=lineage, out=out, ask=None)
        await follower.attach()
        await _eventually(lambda: any(r.action == "attached" for r in routed))
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())

        hub.apply(DecideResolved(cast_id="child0000", request_id="q1", answer="no"))
        hub.apply(CastGoodbye(cast_id="child0000", status="ok"))

        assert await asyncio.wait_for(follower.until_settled(), timeout=2)
        assert out.getvalue() == (
            "[ci_watch child000] ⏸ push? — answer it in `vekna`\n"
            "[ci_watch child000] ✓ done\n"
        )
        await follower.close()
        await server.close()

    @staticmethod
    async def test_an_answer_given_after_the_daemon_went_goes_nowhere(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        asker = _Asker()
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=asker,
        )
        await follower.attach()
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())
        await _eventually(lambda: bool(asker.asked))
        await server.close()
        assert not await asyncio.wait_for(follower.until_settled(), timeout=2)

        asker.released.set()
        for _ in range(20):
            await asyncio.sleep(0)

        assert asker.asked == ["[ci_watch child000] push?"]
        assert asker.cancelled == 0
        await follower.close()

    @staticmethod
    async def test_a_prompt_answered_at_the_cast_is_no_longer_asked_here(
        socket_path: Path,
    ):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        asker = _Asker()
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=asker,
        )
        await follower.attach()
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())
        await _eventually(lambda: bool(asker.asked))

        hub.apply(DecideResolved(cast_id="child0000", request_id="q1", answer="no"))
        await _eventually(lambda: asker.cancelled == 1)

        assert asker.asked == ["[ci_watch child000] push?"]
        await follower.close()
        await server.close()

    @staticmethod
    async def test_a_prompt_replayed_while_asked_is_not_asked_twice(socket_path: Path):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        asker = _Asker()
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=asker,
        )
        await follower.attach()
        hub.apply(_hello("child0000", by="root"))
        hub.apply(_asked())
        await _eventually(lambda: bool(asker.asked))

        hub.apply(GrimoireBegin(cast_id="child0000"))
        hub.apply(_asked())
        hub.apply(GrimoireEnd(cast_id="child0000"))
        hub.apply(CastGoodbye(cast_id="child0000", status="ok"))

        assert await asyncio.wait_for(follower.until_settled(), timeout=2)
        assert asker.asked == ["[ci_watch child000] push?"]
        assert asker.cancelled == 0
        await follower.close()
        await server.close()

    @staticmethod
    async def test_a_prompt_it_cannot_ask_says_where_to_answer(socket_path: Path):
        hub = Hub()
        server = await serve(path=socket_path, routes=hub)
        peer = _Peer()
        out = io.StringIO()
        follower = Follower(
            socket_path=socket_path, lineage=Lineage("root"), out=out, ask=_Refuser()
        )
        await follower.attach()
        hub.open_cast("child0000", peer)
        hub.apply(_hello("child0000", by="root"))

        hub.apply(_asked())
        await _eventually(lambda: bool(out.getvalue()))

        assert out.getvalue() == (
            "[ci_watch child000] no terminal to ask on — answer it in `vekna`\n"
        )
        assert not peer.sent
        await follower.close()
        await server.close()
