import asyncio

import pytest

from vekna.gates.cli.dashboard import Dashboard
from vekna.mills.hub import Hub
from vekna.pacts.screen import Screen


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
