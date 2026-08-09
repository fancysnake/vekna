import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner

from vekna.inits.cli import daemon, init_command
from vekna.links.socket_server import attach
from vekna.pacts.screen import Screen
from vekna.wire import (
    CastGoodbye,
    CastHello,
    DecideRequested,
    RiteFinished,
    RiteStarted,
    WireMessage,
    encode_frame,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 400
_TICK = 0.01


def _hello(cast_id: str = "c1", ritual: str = "fix_demo") -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/home/someone/proj",
        ritual=ritual,
        components={},
        started_at=_WHEN,
    )


def _started(cast_id: str = "c1") -> RiteStarted:
    return RiteStarted(
        cast_id=cast_id,
        rite_id="r1",
        parent_id=None,
        name="run_tests",
        category="step",
        started_at=_WHEN,
    )


# A terminal nobody is sitting at until the test types. Reading blocks on the
# queue, which is what a real one does between keystrokes.
class _Keys(Screen):
    def __init__(self) -> None:
        self.frames: list[str] = []
        self._typed: asyncio.Queue[str | None] = asyncio.Queue()

    def show(self, screen: str) -> None:
        self.frames.append(screen)

    async def read_line(self) -> str | None:
        return await self._typed.get()

    def press(self, key: str) -> None:
        self._typed.put_nowait(key)

    def painted(self, text: str) -> bool:
        return any(text in frame for frame in self.frames)


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    raise AssertionError(ready)


async def _say(path: Path, *messages: WireMessage) -> asyncio.StreamWriter:
    _, writer = await attach(path)
    for message in messages:
        writer.write(encode_frame(message))
    await writer.drain()
    return writer


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    return tmp_path / "vekna.sock"


@pytest.mark.asyncio
class TestTheView:
    @staticmethod
    async def test_a_cast_appears_and_the_daemon_can_be_quit(socket_path: Path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(socket_path.exists)

        writer = await _say(socket_path, _hello(), _started())
        await _eventually(lambda: keys.painted("fix_demo"))
        keys.press("q")

        assert await running == 0
        assert keys.painted("vekna — 1 cast")
        writer.close()

    @staticmethod
    async def test_a_number_drills_in_and_b_comes_back(socket_path: Path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(socket_path.exists)
        writer = await _say(
            socket_path,
            _hello(),
            _started(),
            RiteStarted(
                cast_id="c1",
                rite_id="r2",
                parent_id="r1",
                name="shell",
                category="medium",
                started_at=_WHEN,
            ),
            RiteFinished(cast_id="c1", rite_id="r2", status="ok", finished_at=_WHEN),
        )
        await _eventually(lambda: keys.painted("fix_demo"))

        keys.press("1")
        # The medium sits under the step that opened it.
        await _eventually(lambda: keys.painted("   ↳ shell"))
        keys.press("b")
        await _eventually(lambda: keys.painted("b back") is not None)
        keys.press("q")

        await running
        assert keys.painted("/home/someone/proj")
        writer.close()

    @staticmethod
    async def test_a_waiting_cast_says_where_to_answer_it(socket_path: Path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(socket_path.exists)

        writer = await _say(
            socket_path,
            _hello(),
            _started(),
            DecideRequested(
                cast_id="c1", rite_id="r1", request_id="q1", prompt="allow Bash?"
            ),
        )
        await _eventually(lambda: keys.painted("waiting: allow Bash?"))
        keys.press("1")
        await _eventually(lambda: keys.painted("answer it where the cast was started"))
        keys.press("q")

        await running
        writer.close()

    @staticmethod
    async def test_a_key_that_means_nothing_says_so(socket_path: Path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(socket_path.exists)

        keys.press("zz")
        await _eventually(lambda: keys.painted("is not a cast"))
        keys.press("9")
        await _eventually(lambda: keys.painted("there is no cast 9"))
        keys.press("q")

        assert await running == 0

    @staticmethod
    async def test_an_empty_daemon_says_it_is_empty(socket_path: Path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(lambda: keys.painted("no casts"))
        bound = await asyncio.to_thread(socket_path.exists)

        keys.press("q")

        assert await running == 0
        assert bound


@pytest.mark.asyncio
class TestPeers:
    @staticmethod
    async def test_a_second_vekna_sees_the_same_casts(socket_path: Path):
        host_keys, peer_keys = _Keys(), _Keys()
        host = asyncio.create_task(daemon(screen=host_keys))
        await _eventually(socket_path.exists)
        writer = await _say(socket_path, _hello(), _started())
        await _eventually(lambda: host_keys.painted("fix_demo"))

        peer = asyncio.create_task(daemon(screen=peer_keys))
        await _eventually(lambda: peer_keys.painted("fix_demo"))

        assert peer_keys.painted("attached to the vekna already running here")
        peer_keys.press("q")
        assert await peer == 0
        host_keys.press("q")
        await host
        writer.close()

    @staticmethod
    async def test_a_peer_is_told_when_the_daemon_ends(socket_path: Path):
        host_keys, peer_keys = _Keys(), _Keys()
        host = asyncio.create_task(daemon(screen=host_keys))
        await _eventually(socket_path.exists)
        peer = asyncio.create_task(daemon(screen=peer_keys))
        await _eventually(lambda: peer_keys.painted("attached to the vekna"))

        host_keys.press("q")
        await host

        await _eventually(lambda: peer_keys.painted("the daemon ended"))
        assert await peer == 0


@pytest.mark.asyncio
class TestDebug:
    @staticmethod
    async def test_it_logs_every_event_including_the_dropped_ones(
        socket_path: Path, tmp_path: Path
    ):
        log = tmp_path / "debug.log"
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys, debug=log))
        await _eventually(socket_path.exists)

        writer = await _say(
            socket_path,
            _hello(),
            _started(),
            CastGoodbye(cast_id="c1", status="ok"),
            _started("gone"),
        )
        await _eventually(lambda: log.is_file() and "no such cast" in log.read_text())
        keys.press("q")

        await running
        written = log.read_text()
        assert "c1 cast_hello applied" in written
        assert "gone rite_started dropped (no such cast)" in written
        assert keys.painted(f"logging every event to {log}")
        writer.close()

    @staticmethod
    async def test_without_the_flag_nothing_is_written(socket_path: Path, tmp_path):
        keys = _Keys()
        running = asyncio.create_task(daemon(screen=keys))
        await _eventually(socket_path.exists)
        writer = await _say(socket_path, _hello())
        await _eventually(lambda: keys.painted("fix_demo"))

        keys.press("q")

        await running
        assert not (tmp_path / "debug.log").exists()
        writer.close()


class TestTheBareCommand:
    # The whole path a person takes: `vekna`, a real terminal, and `q`.
    @staticmethod
    def test_it_is_the_daemon_and_quits_on_q(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
        monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))

        result = CliRunner().invoke(init_command(), [], input="q\n")

        assert result.exit_code == 0
        assert "no casts" in result.output


class TestCastsCommand:
    @staticmethod
    def test_it_lists_what_the_daemon_wrote_down(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
        monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
        journal = tmp_path / "runs" / "c1"
        journal.mkdir(parents=True)
        (journal / "run.json").write_text(
            f'{{"hello": {_hello().model_dump_json()}, "status": "ok"}}'
        )

        result = CliRunner().invoke(init_command(), ["casts"])

        assert result.exit_code == 0
        assert "fix_demo" in result.output
        assert "c1" in result.output

    @staticmethod
    def test_nothing_recorded_says_nothing_recorded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))

        result = CliRunner().invoke(init_command(), ["casts"])

        assert result.exit_code == 0
        assert result.output.strip() == "no casts recorded"
