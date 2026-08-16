import asyncio
from datetime import UTC, datetime

import pytest

from vekna.gates.cli.dashboard import Dashboard
from vekna.mills.hub import Hub
from vekna.pacts.screen import Screen
from vekna.wire import CastGoodbye, CastHello


class _Keys(Screen):
    def __init__(self, *typed: str) -> None:
        self.frames: list[str] = []
        self._typed = list(typed)

    def show(self, screen: str) -> None:
        self.frames.append(screen)

    async def read_line(self) -> str | None:
        if not self._typed:
            return None
        return self._typed.pop(0)


def _dashboard(*typed: str) -> tuple[Dashboard, _Keys]:
    keys = _Keys(*typed)
    return Dashboard(casts=Hub(), screen=keys), keys


def _hello(cast_id: str, ritual: str) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/proj",
        ritual=ritual,
        components={},
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
class TestPicking:
    # The listing puts running casts first and the hub holds them in the order
    # they arrived. Numbered off the hub, `1` drilled into whichever cast was
    # heard first — not the one printed on the line the operator read.
    @staticmethod
    async def test_the_number_typed_is_the_line_painted():
        hub = Hub()
        hub.apply(_hello("c1", "finished_first"))
        hub.apply(CastGoodbye(cast_id="c1", status="ok"))
        hub.apply(_hello("c2", "still_going"))
        keys = _Keys("1", "q")

        await asyncio.wait_for(Dashboard(casts=hub, screen=keys).run(), timeout=2)

        assert any("vekna — still_going" in frame for frame in keys.frames)


@pytest.mark.asyncio
class TestLoops:
    @staticmethod
    async def test_painting_ends_itself_once_the_view_is_stopped():
        dashboard, keys = _dashboard()
        painting = asyncio.create_task(dashboard.painting())
        dashboard.changed()

        dashboard.stop(note="done here")

        await asyncio.wait_for(painting, timeout=2)
        assert any("done here" in frame for frame in keys.frames)

    @staticmethod
    async def test_typing_gives_up_when_there_is_nobody_to_ask():
        dashboard, _ = _dashboard()

        await asyncio.wait_for(dashboard.typing(), timeout=2)

        # Nobody typed `q`, so the view is still live — it just has no keys.
        assert not dashboard.stopped

    @staticmethod
    async def test_typing_ends_on_quit():
        dashboard, _ = _dashboard("b", "q", "ignored")

        await asyncio.wait_for(dashboard.typing(), timeout=2)

        assert dashboard.stopped

    # Enter on its own is not a mistake worth a message.
    @staticmethod
    async def test_an_empty_line_says_nothing():
        dashboard, keys = _dashboard("", "q")

        await asyncio.wait_for(dashboard.typing(), timeout=2)

        assert not any("is not a cast" in frame for frame in keys.frames)

    # `"²".isdigit()` is true and `int("²")` raises, which ended the input task
    # and left a view that painted but took no more keys.
    @staticmethod
    async def test_a_digit_int_will_not_take_is_just_a_bad_key():
        dashboard, keys = _dashboard("²", "q")

        await asyncio.wait_for(dashboard.typing(), timeout=2)

        assert dashboard.stopped
        assert any("is not a cast" in frame for frame in keys.frames)

    @staticmethod
    async def test_run_ends_when_the_view_does():
        dashboard, keys = _dashboard("q")

        await asyncio.wait_for(dashboard.run(), timeout=2)

        assert dashboard.stopped
        assert keys.frames

    # A peer's reader hitting a frame it cannot decode is this: the task dies
    # and sets nothing, so without the watch the view waits for a stop that is
    # never coming.
    @staticmethod
    async def test_run_ends_when_a_task_beside_it_fails():
        dashboard, keys = _dashboard()

        async def breaks() -> None:
            await asyncio.sleep(0)
            msg = "no such kind"
            raise ValueError(msg)

        await asyncio.wait_for(
            dashboard.run(alongside=[asyncio.create_task(breaks())]), timeout=2
        )

        assert dashboard.stopped
        assert any("no such kind" in frame for frame in keys.frames)

    # Nobody is typing, which is not a failure: the daemon still has casts to
    # serve, and the view is still worth painting.
    @staticmethod
    async def test_a_task_that_ends_on_its_own_does_not_stop_the_view():
        dashboard, _ = _dashboard()
        running = asyncio.create_task(dashboard.run())
        await asyncio.sleep(0)

        assert not dashboard.stopped

        dashboard.stop()
        await asyncio.wait_for(running, timeout=2)
