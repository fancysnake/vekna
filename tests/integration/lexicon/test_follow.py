import asyncio
import io
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from vekna.lexicon._links.follow import Follower
from vekna.lexicon._mills.follow import Lineage
from vekna.links.socket_server import serve
from vekna.mills.hub import Hub
from vekna.pacts.routing import Routed, Surface
from vekna.wire import (
    CastGoodbye,
    CastHello,
    DecideClaimed,
    DecideRequested,
    DecideResolved,
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
    async def test_with_no_daemon_there_is_nothing_to_follow(socket_path: Path):
        follower = Follower(
            socket_path=socket_path,
            lineage=Lineage("root"),
            out=io.StringIO(),
            ask=None,
        )

        assert not await follower.attach()


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
