import logging
import signal
from datetime import UTC, datetime

import pytest

from vekna.mills.cutter import Cutter
from vekna.mills.hub import Hub
from vekna.wire import CastGoodbye, CastHello

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _hello(pid: int | None) -> CastHello:
    return CastHello(
        cast_id="c1",
        project_root="/proj",
        project="/proj/.git",
        ritual="pr_fix",
        components={},
        started_at=_WHEN,
        wired=True,
        pid=pid,
    )


def _warned(caplog: pytest.LogCaptureFixture) -> list[str]:
    assert {record.levelno for record in caplog.records} == {logging.WARNING}
    return [record.getMessage() for record in caplog.records]


# The process side of a cut: which pids are alive and what was sent to them. A
# signal stops the pid it is sent to only when told to,
# and reaches it at all only when the pid is this daemon's to signal.
class _Processes:
    def __init__(
        self, *, stops_on: set[int] | None = None, permitted: bool = True
    ) -> None:
        self.alive: set[int] = {41, 42}
        self.sent: list[tuple[int, int]] = []
        self._stops_on = stops_on or set()
        self._permitted = permitted

    def kill(self, pid: int, signum: int) -> bool:
        if not self._permitted:
            return False
        self.sent.append((pid, signum))
        if signum in self._stops_on:
            self.alive.discard(pid)
        return True

    def cutter(self, hub: Hub) -> Cutter:
        return Cutter(casts=hub, alive=self.alive.__contains__, kill=self.kill, grace=0)


@pytest.mark.asyncio
class TestCutting:
    @staticmethod
    async def test_a_cast_that_ends_itself_is_not_signalled(
        caplog: pytest.LogCaptureFixture,
    ):
        hub = Hub()
        hub.apply(_hello(pid=42))
        hub.apply(CastGoodbye(cast_id="c1", status="error", detail="cancelled"))
        processes = _Processes()

        await processes.cutter(hub).cut("c1")

        assert not processes.sent
        assert not caplog.records

    @staticmethod
    async def test_a_cast_deaf_to_the_ask_is_sent_ctrl_c(
        caplog: pytest.LogCaptureFixture,
    ):
        hub = Hub()
        hub.apply(_hello(pid=42))
        processes = _Processes(stops_on={signal.SIGINT})

        await processes.cutter(hub).cut("c1")

        assert processes.sent == [(42, signal.SIGINT)]
        assert _warned(caplog) == ["cast c1 still running: sent SIGINT to 42"]

    @staticmethod
    async def test_a_cut_asked_twice_signals_once():
        hub = Hub()
        hub.apply(_hello(pid=42))
        processes = _Processes()
        cutter = processes.cutter(hub)

        first, second = cutter.cut("c1"), cutter.cut("c1")
        await first

        assert first is second
        assert processes.sent == [(42, signal.SIGINT), (42, signal.SIGKILL)]

    @staticmethod
    async def test_one_that_outlives_ctrl_c_is_killed():
        hub = Hub()
        hub.apply(_hello(pid=42))
        processes = _Processes()

        await processes.cutter(hub).cut("c1")

        assert processes.sent == [(42, signal.SIGINT), (42, signal.SIGKILL)]

    # A pid this daemon may not signal is still a running cast, not a dead one.
    @staticmethod
    async def test_a_live_pid_that_will_not_take_a_signal_is_said_as_such(
        caplog: pytest.LogCaptureFixture,
    ):
        hub = Hub()
        hub.apply(_hello(pid=42))
        processes = _Processes(permitted=False)

        await processes.cutter(hub).cut("c1")

        assert not processes.sent
        assert _warned(caplog) == [
            "cast c1 still running: could not send SIGINT to 42",
            "cast c1 still running: could not send SIGKILL to 42",
        ]

    @staticmethod
    async def test_with_no_pid_anywhere_it_says_so(caplog: pytest.LogCaptureFixture):
        hub = Hub()
        hub.apply(_hello(pid=None))
        processes = _Processes()

        await processes.cutter(hub).cut("c1")

        assert not processes.sent
        assert _warned(caplog) == [
            "cast c1 has no pid to signal: stop it at its terminal"
        ]

    @staticmethod
    async def test_a_cast_the_daemon_does_not_know_is_left_alone(
        caplog: pytest.LogCaptureFixture,
    ):
        processes = _Processes()

        await processes.cutter(Hub()).cut("c1")

        assert not processes.sent
        assert not caplog.records

    # Once one cut has ended, a cast asked to stop again is cut again.
    @staticmethod
    async def test_a_cut_asked_after_the_last_one_ended_signals_again():
        hub = Hub()
        hub.apply(_hello(pid=42))
        processes = _Processes(stops_on={signal.SIGINT})
        cutter = processes.cutter(hub)
        await cutter.cut("c1")
        processes.alive.add(42)

        await cutter.cut("c1")

        assert processes.sent == [(42, signal.SIGINT), (42, signal.SIGINT)]
