import asyncio
import contextlib
import os
import shutil
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command, serve_daemon, stop_daemon, window
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach
from vekna.pacts.screen import Screen
from vekna.wire import (
    CastGoodbye,
    CastHello,
    DecideRequested,
    RiteFinished,
    RiteStarted,
    StopRequested,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 400
_TICK = 0.01


# Of the project the test is standing in unless told otherwise, which is the
# one a bare `vekna` there opens on: the fixture stands it in no repository, so
# that is the directory itself.
def _hello(
    cast_id: str = "c1",
    ritual: str = "fix_demo",
    started_at: datetime = _WHEN,
    project: str | None = None,
) -> CastHello:
    return CastHello(
        cast_id=cast_id,
        project_root="/home/someone/proj",
        ritual=ritual,
        components={},
        started_at=started_at,
        project=project if project is not None else str(Path.cwd().resolve()),
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

    # What is on screen now, as opposed to what has ever been on it: going back
    # to the list is only visible in the last frame, since the frame that
    # drilled in is still in `frames` either way.
    def showing(self, text: str) -> bool:
        return bool(self.frames) and text in self.frames[-1]


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s waiting for the view to catch up"
    raise AssertionError(msg)


async def _say(path: Path, *messages: WireMessage) -> asyncio.StreamWriter:
    _, writer = await attach(path)
    for message in messages:
        writer.write(encode_frame(message))
    await writer.drain()
    return writer


# The daemon in this process, headless, and stopped the way `vekna stop` does
# it — which is also what proves it was still up after every `q` in the test.
@contextlib.asynccontextmanager
async def _served(
    socket_path: Path, *, debug: Path | None = None
) -> AsyncGenerator[asyncio.Task[int]]:
    host = asyncio.create_task(serve_daemon(debug=debug))
    await _eventually(socket_path.exists)
    try:
        yield host
    finally:
        await stop_daemon()
        await host


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "vekna.sock"


@pytest.mark.asyncio
class TestTheView:
    @staticmethod
    async def test_q_leaves_the_daemon_running(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path) as host:
            writer = await _say(socket_path, _hello(), _started())
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("fix_demo"))

            keys.press("q")

            assert await peer == 0
            assert not host.done()
            assert await alive(socket_path)
            writer.close()
        assert keys.painted("vekna — 1 running")
        assert await host == 0

    @staticmethod
    async def test_a_number_drills_in_and_b_comes_back(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path):
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
                RiteFinished(
                    cast_id="c1", rite_id="r2", status="ok", finished_at=_WHEN
                ),
            )
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("fix_demo"))

            keys.press("1")
            # The medium sits under the step that opened it.
            await _eventually(lambda: keys.showing("   ↳ shell"))
            assert keys.showing("/home/someone/proj")
            keys.press("b")
            # Back where it started: the cast list, not the cast.
            await _eventually(lambda: keys.showing("number to drill in"))
            keys.press("q")

            await peer
            writer.close()
        assert not keys.frames[-1].endswith("b back · q quit\n")

    @staticmethod
    async def test_a_waiting_cast_says_where_to_answer_it(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path):
            writer = await _say(
                socket_path,
                _hello(),
                _started(),
                DecideRequested(
                    cast_id="c1", rite_id="r1", request_id="q1", prompt="allow Bash?"
                ),
            )
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("waiting"))
            await _eventually(lambda: keys.painted("allow Bash?"))
            keys.press("1")
            await _eventually(
                lambda: keys.painted("answer it where the cast was started")
            )
            keys.press("q")

            await peer
            writer.close()

    @staticmethod
    async def test_a_key_that_means_nothing_says_so(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))

            keys.press("zz")
            await _eventually(lambda: keys.painted("is not a cast"))
            keys.press("9")
            await _eventually(lambda: keys.painted("there is no cast 9"))
            keys.press("q")

            assert await peer == 0

    @staticmethod
    async def test_an_empty_daemon_says_it_is_empty(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("no casts"))

            keys.press("q")

            assert await peer == 0


@pytest.mark.asyncio
class TestProjects:
    @staticmethod
    async def test_the_view_opens_on_its_own_project_and_g_shows_every_one(
        socket_path: Path, tmp_path: Path
    ):
        elsewhere = str(tmp_path / "other" / ".git")
        keys = _Keys()
        async with _served(socket_path):
            here = await _say(socket_path, _hello("c1", "mine"))
            there = await _say(socket_path, _hello("c2", "theirs", project=elsewhere))
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("mine"))
            assert not keys.painted("theirs")
            assert keys.showing(f"({tmp_path.name})")

            keys.press("g")
            await _eventually(lambda: keys.showing("theirs"))
            assert keys.showing("(all projects)")
            keys.press("p")
            await _eventually(lambda: not keys.showing("theirs"))
            keys.press("q")

            await peer
            here.close()
            there.close()

    # The number typed is a position in what is on screen, and the cast of
    # another project is not on it.
    @staticmethod
    async def test_numbers_count_only_the_casts_shown(
        socket_path: Path, tmp_path: Path
    ):
        elsewhere = str(tmp_path / "other" / ".git")
        keys = _Keys()
        async with _served(socket_path):
            there = await _say(socket_path, _hello("c2", "theirs", project=elsewhere))
            here = await _say(socket_path, _hello("c1", "mine"))
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("mine"))

            keys.press("1")
            await _eventually(lambda: keys.showing("vekna — mine"))
            keys.press("q")

            await peer
            here.close()
            there.close()


@pytest.mark.asyncio
class TestPeers:
    @staticmethod
    async def test_two_windows_see_the_same_casts(socket_path: Path):
        first, second = _Keys(), _Keys()
        async with _served(socket_path):
            writer = await _say(socket_path, _hello(), _started())
            one = asyncio.create_task(window(screen=first))
            two = asyncio.create_task(window(screen=second))
            await _eventually(lambda: first.painted("fix_demo"))
            await _eventually(lambda: second.painted("fix_demo"))

            first.press("q")
            second.press("q")

            assert await one == 0
            assert await two == 0
            writer.close()

    @staticmethod
    async def test_a_window_is_told_when_the_daemon_ends(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path) as host:
            peer = asyncio.create_task(window(screen=keys))
            await _eventually(lambda: keys.painted("no casts"))

        await _eventually(lambda: keys.painted("the daemon ended"))
        assert await peer == 0
        assert await host == 0

    @staticmethod
    async def test_debug_asked_of_a_running_daemon_says_it_is_too_late(
        socket_path: Path,
    ):
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(debug=True, screen=keys))
            await _eventually(lambda: keys.painted("--debug ignored"))

            keys.press("q")

            assert await peer == 0

    # The handshake this end wrote is the one frame kind that cannot come back,
    # and a peer that took it for a cast would paint one that is not there. The
    # daemon on the other end is a stub, because a real one never sends it.
    @staticmethod
    async def test_a_peer_ignores_its_own_handshake_coming_back(socket_path: Path):
        hello = _hello()

        # Closed when the peer hangs up: 3.12's `Server.wait_closed` comes back
        # only once every connection the server handed out is closed, and a stub
        # that leaves its own open never comes back from it at all.
        async def echoes(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            with contextlib.suppress(OSError):
                async for _ in read_frames(reader):
                    writer.write(encode_frame(SurfaceHello()))
                    writer.write(encode_frame(hello))
                    await writer.drain()
            writer.close()

        server = await asyncio.start_unix_server(echoes, path=str(socket_path))
        peer_keys = _Keys()
        peer = asyncio.create_task(window(screen=peer_keys))
        await _eventually(lambda: peer_keys.painted("fix_demo"))

        peer_keys.press("q")

        assert await peer == 0
        assert peer_keys.painted("vekna — 1 running")
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
class TestServing:
    # Two windows summoning at once: the lock is taken before either binds, so
    # the loser refuses even where the winner is not listening yet.
    @staticmethod
    async def test_a_second_daemon_refuses_while_the_first_holds_the_lock(
        socket_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        async with _served(socket_path):
            assert await serve_daemon() == 1

            assert await alive(socket_path)
        lock = tmp_path / "state" / "vekna" / "daemon.lock"
        assert f"another daemon holds {lock}" in capsys.readouterr().err

    # A daemon keeping its state elsewhere holds a lock this one cannot see,
    # and a bind would still take its socket.
    @staticmethod
    async def test_a_second_daemon_refuses_rather_than_takes_the_socket(
        socket_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        async with _served(socket_path):
            monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "elsewhere"))
            assert await serve_daemon() == 1

            assert await alive(socket_path)
        assert f"a daemon is already listening on {socket_path}" in (
            capsys.readouterr().err
        )

    @staticmethod
    async def test_stop_with_nothing_running_says_so(socket_path: Path):
        assert not await alive(socket_path)

        assert await stop_daemon() == "no daemon running"

    # The stub takes the stop and goes on listening, which is what a daemon
    # wedged on its way out looks like from here.
    @staticmethod
    async def test_stop_says_so_when_the_daemon_keeps_answering(
        socket_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("vekna.inits.cli._POLLS", 3)
        heard: list[WireMessage] = []

        async def ignores(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            with contextlib.suppress(OSError):
                heard.extend([frame async for frame in read_frames(reader)])
            writer.close()

        server = await asyncio.start_unix_server(ignores, path=str(socket_path))
        try:
            with pytest.raises(click.ClickException) as raised:
                await stop_daemon()
        finally:
            server.close()
            await server.wait_closed()

        assert raised.value.message == (
            f"asked the daemon to stop, and {socket_path} is still answering"
        )
        assert heard == [StopRequested()]

    # In-process, as the forked child: run off the loop's thread, since the
    # command starts a loop of its own.
    @staticmethod
    async def test_serve_as_the_child_detaches_and_logs_where_debug_goes(
        socket_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        forks: list[None] = []
        sessions: list[None] = []

        def fork() -> int:
            forks.append(None)
            return 0

        monkeypatch.setattr(os, "fork", fork)
        monkeypatch.setattr(os, "setsid", lambda: sessions.append(None))
        served = asyncio.create_task(
            asyncio.to_thread(CliRunner().invoke, init_command(), ["serve", "--debug"])
        )
        await _eventually(socket_path.exists)

        assert await stop_daemon() == "stopped the daemon"
        result = await served

        log = tmp_path / "state" / "vekna" / "debug.log"
        assert result.exit_code == 0
        assert f"logging every event to {log}" in result.stderr
        assert forks == [None]
        assert sessions == [None]


@pytest.mark.asyncio
class TestDebug:
    @staticmethod
    async def test_it_logs_every_event_including_the_dropped_ones(
        socket_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        log = tmp_path / "debug.log"
        async with _served(socket_path, debug=log):
            writer = await _say(
                socket_path,
                _hello(),
                _started(),
                CastGoodbye(cast_id="c1", status="ok"),
            )
            # Its own connection, because a rite for a cast this daemon never
            # met is only reachable as an opening frame — a connection that has
            # said which cast it is cannot then speak for another one.
            stray = await _say(socket_path, _started("gone"))
            await _eventually(
                lambda: log.is_file() and "no such cast" in log.read_text()
            )
            writer.close()
            stray.close()

        written = log.read_text()
        assert "c1 cast_hello applied" in written
        assert "gone rite_started dropped (no such cast)" in written
        assert f"logging every event to {log}" in capsys.readouterr().err

    @staticmethod
    async def test_without_the_flag_nothing_is_written(socket_path: Path, tmp_path):
        async with _served(socket_path):
            writer = await _say(socket_path, _hello())
            writer.close()

        assert not (tmp_path / "debug.log").exists()


@pytest.mark.asyncio
class TestPruning:
    @staticmethod
    async def test_a_runs_root_that_will_not_clean_is_said_and_the_daemon_starts(
        socket_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        monkeypatch.setattr("vekna.inits.cli._KEPT", 1)
        journal = Journal(tmp_path / "runs")
        for index in range(2):
            journal.record(
                _hello(f"c{index}", started_at=_WHEN + timedelta(minutes=index))
            )
            journal.record(CastGoodbye(cast_id=f"c{index}", status="ok"))

        def rmtree(*_args: object, ignore_errors: bool = False) -> None:
            if not ignore_errors:
                raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(shutil, "rmtree", rmtree)
        async with _served(socket_path):
            assert await alive(socket_path)

        said = capsys.readouterr().err
        assert "could not prune 1 old cast(s): " in said
        assert f"{tmp_path / 'runs' / 'c0'}: [Errno 13] Permission denied" in said


# The whole path a person takes: a real `vekna`, a daemon in a process of its
# own, `q`, and `vekna stop`.
class TestTheBareCommand:
    @staticmethod
    def test_it_starts_a_daemon_that_outlives_q_and_stop_ends_it(
        socket_path: Path, tmp_path: Path
    ):
        try:
            started = CliRunner().invoke(init_command(), [], input="q\n")
            still_up = asyncio.run(alive(socket_path))
        finally:
            stopped = CliRunner().invoke(init_command(), ["stop"])

        assert started.exit_code == 0
        assert "started the daemon" in started.output
        assert "no casts" in started.output
        assert still_up
        assert stopped.exit_code == 0
        assert stopped.output.strip() == "stopped the daemon"
        assert not asyncio.run(alive(socket_path))
        assert "listening on" in (tmp_path / "state/vekna/daemon.log").read_text()

    @staticmethod
    def test_a_daemon_that_cannot_bind_is_said_with_its_log(
        socket_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("vekna.inits.cli._POLLS", 10)
        socket_path.write_text("somebody's file", encoding="utf-8")

        result = CliRunner().invoke(init_command(), [], input="q\n")

        log = tmp_path / "state/vekna/daemon.log"
        assert result.exit_code == 1
        assert f"the daemon is not listening on {socket_path}" in result.output
        assert f"{log} says why" in result.output
        assert socket_path.read_text(encoding="utf-8") == "somebody's file"

    @staticmethod
    def test_a_launch_that_fails_says_so_with_its_log(
        socket_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("vekna.inits.cli._CLI_MODULE", "vekna.no_such_module")

        result = CliRunner().invoke(init_command(), [], input="q\n")

        log = tmp_path / "state/vekna/daemon.log"
        assert result.exit_code == 1
        assert f"the daemon would not start (1) — {log} says why" in result.output
        assert "No module named vekna.no_such_module" in log.read_text(encoding="utf-8")
        assert not socket_path.exists()

    @staticmethod
    def test_serve_as_the_parent_returns_at_once(
        socket_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        forks: list[None] = []
        sessions: list[None] = []

        def fork() -> int:
            forks.append(None)
            return 4242

        monkeypatch.setattr(os, "fork", fork)
        monkeypatch.setattr(os, "setsid", lambda: sessions.append(None))

        result = CliRunner().invoke(init_command(), ["serve"])

        assert result.exit_code == 0
        assert not result.output
        assert forks == [None]
        assert not sessions
        assert not socket_path.exists()


class TestTheLogCommand:
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

        result = CliRunner().invoke(init_command(), ["log"])

        assert result.exit_code == 0
        assert "fix_demo" in result.output
        assert "c1" in result.output

    @staticmethod
    def test_nothing_recorded_says_nothing_recorded(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))

        result = CliRunner().invoke(init_command(), ["log"])

        assert result.exit_code == 0
        assert result.output.strip() == "no casts recorded"
