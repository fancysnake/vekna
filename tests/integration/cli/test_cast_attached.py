import asyncio
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from vekna.lexicon._inits import main
from vekna.links.socket_server import serve
from vekna.mills.hub import Hub
from vekna.pacts.casts import CastView

_RITUALS = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import Transition, done, goto, ritual, step


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int


    @step
    async def tick(state: Tick) -> Transition:
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(components: Countdown) -> Transition:
        return goto(tick, Tick(left=components.start))
    """)

_SPINNER = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, goto, ritual, step


    class Spin(BaseModel):
        pass


    @step
    async def spin(state: Spin) -> Transition:
        return goto(spin, state)


    @ritual("spinner", max_steps=2)
    async def spinner(_: NoComponents) -> Transition:
        return goto(spin, Spin())
    """)

_POLL_SECONDS = 0.01
_PATIENCE = 500


# A daemon on its own loop in its own thread, because that is what it is: the
# cast process has a loop of its own and the two only meet on the socket.
class _DaemonThread:
    def __init__(self, path: Path) -> None:
        self.hub = Hub()
        self._path = path
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(timeout=5)

    def stop(self) -> None:
        assert self._loop is not None
        assert self._stop is not None
        self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=5)

    @staticmethod
    def wait_for(ready: Callable[[], bool]) -> None:
        for _ in range(_PATIENCE):
            if ready():
                return
            time.sleep(_POLL_SECONDS)
        raise AssertionError(ready)

    def only_cast(self) -> CastView:
        return next(iter(self.hub.casts.values()))

    def _run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        server = await serve(
            path=self._path,
            on_message=self.hub.apply,
            on_attach=self.hub.attach_surface,
            on_detach=self.hub.detach_surface,
        )
        assert server is not None
        self._ready.set()
        await self._stop.wait()
        await server.close()


@pytest.fixture(name="daemon")
def _daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    running = _DaemonThread(tmp_path / "vekna.sock")
    running.start()

    yield running

    running.stop()


class TestAttachedCast:
    @staticmethod
    def test_the_daemon_sees_the_cast_it_never_started(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, daemon: _DaemonThread
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["countdown", "--start", "1"])

        assert exit_code == 0
        daemon.wait_for(lambda: bool(daemon.hub.casts))
        daemon.wait_for(lambda: daemon.only_cast().status == "ok")
        view = daemon.only_cast()
        assert view.hello.ritual == "countdown"
        assert view.hello.components == {"start": 1}
        assert [rite.started.name for rite in view.rites.values()] == ["tick", "tick"]

    @staticmethod
    def test_a_cast_that_fails_says_so_on_its_way_out(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, daemon: _DaemonThread
    ):
        (tmp_path / "rituals.py").write_text(_SPINNER)
        monkeypatch.chdir(tmp_path)

        exit_code = main(["spinner"])

        assert exit_code == 1
        daemon.wait_for(lambda: bool(daemon.hub.casts))
        daemon.wait_for(lambda: daemon.only_cast().status == "error")
        assert "max_steps" in (daemon.only_cast().detail or "")

    @staticmethod
    def test_the_cast_still_prints_its_own_tree(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        daemon: _DaemonThread,
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)
        monkeypatch.chdir(tmp_path)

        main(["countdown", "--start", "1"])

        # Attaching adds a listener, it does not move the output.
        assert "tick" in capsys.readouterr().out
        daemon.wait_for(lambda: bool(daemon.hub.casts))
