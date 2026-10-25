import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from vekna.inits.cli import init_command, tui_window, window
from vekna.inits.daemon import CLI_MODULE, serve_daemon, stop_daemon
from vekna.lexicon._inits import _DAEMON_WENT, _FOLLOWING, _LEFT, _drive
from vekna.links.journal import Journal
from vekna.links.socket_server import alive, attach
from vekna.links.spawner import Spawner, pid_alive
from vekna.pacts.casts import DamagedRun
from vekna.pacts.screen import Screen
from vekna.wire import (
    AwaitRequested,
    AwaitWithdrawn,
    CastCancelRequested,
    CastGoodbye,
    CastHello,
    CastQueued,
    CastRefused,
    CastRequested,
    CodingSlotGranted,
    CodingSlotReleased,
    CodingSlotRequested,
    DecideClaimed,
    DecideRequested,
    EnqueueRefused,
    EnqueueRequested,
    RiteFinished,
    RiteStarted,
    RunRecord,
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
            await _eventually(lambda: keys.painted("answering here takes it over"))
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

    # The Textual window ends the same way, rather than drawing a table nobody
    # will ever change again.
    @staticmethod
    async def test_the_drawn_window_ends_with_the_daemon(socket_path: Path):
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log) as host:
            peer = asyncio.create_task(tui_window(headless=True))
            await _eventually(lambda: log.exists() and "attached" in log.read_text())

        assert await asyncio.wait_for(peer, timeout=10) == 0
        assert await host == 0

    @staticmethod
    async def test_the_drawn_window_opens_with_debug_asked_too_late(socket_path: Path):
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log) as host:
            peer = asyncio.create_task(tui_window(debug=True, headless=True))
            await _eventually(lambda: log.exists() and "attached" in log.read_text())

        assert await asyncio.wait_for(peer, timeout=10) == 0
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

    @staticmethod
    async def test_a_window_s_claim_and_cancel_reach_the_cast(
        socket_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        asked = DecideRequested(
            cast_id="c1", request_id="q1", prompt="push?", options=["yes", "no"]
        )
        claimed = DecideClaimed(cast_id="c1", request_id="q1", claim_id="k1")
        cancel = CastCancelRequested(cast_id="c1")
        async with _served(socket_path):
            cast_reader, cast_writer = await attach(socket_path)
            for message in (_hello(), asked):
                cast_writer.write(encode_frame(message))
            await cast_writer.drain()
            surface = await _say(socket_path, SurfaceHello(), claimed, cancel)

            heard: list[WireMessage] = []
            async with asyncio.timeout(10):
                async for message in read_frames(cast_reader):
                    heard.append(message)
                    if message == cancel:
                        break

            assert heard == [claimed, cancel]
            surface.close()
            cast_writer.close()
        assert "cast c1 has no pid to signal" in capsys.readouterr().err

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
    # the loser refuses even where the winner is not listening yet. The lock is
    # the socket's, so keeping state elsewhere is no way past it.
    @staticmethod
    async def test_a_second_daemon_on_the_same_socket_refuses(
        socket_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        async with _served(socket_path):
            monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "elsewhere"))
            assert await serve_daemon() == 1

            assert await alive(socket_path)
        assert f"another daemon holds {socket_path}.lock" in capsys.readouterr().err

    # A sandbox that exports a socket of its own runs a daemon of its own,
    # sharing the state root with the one outside.
    @staticmethod
    async def test_a_daemon_on_another_socket_starts_beside_the_first(
        socket_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        sandboxed = tmp_path / "sandbox.sock"
        async with _served(socket_path):
            with monkeypatch.context() as sandbox:
                sandbox.setenv("VEKNA_SOCKET", str(sandboxed))
                async with _served(sandboxed) as host:
                    assert await alive(sandboxed)
                    assert await alive(socket_path)
                assert await host == 0

    @staticmethod
    async def test_stop_with_nothing_running_says_so(socket_path: Path):
        assert not await alive(socket_path)

        assert await stop_daemon() == "no daemon running"

    # A socket this account may not connect to has somebody behind it, and
    # saying nobody is there would send the operator off to start another.
    @staticmethod
    @pytest.mark.skipif(os.geteuid() == 0, reason="root ignores the socket's mode")
    async def test_stop_says_so_when_the_daemon_cannot_be_reached(socket_path: Path):
        server = await asyncio.start_unix_server(
            lambda _reader, writer: writer.close(), path=str(socket_path)
        )
        await asyncio.to_thread(socket_path.chmod, 0)
        try:
            with pytest.raises(click.ClickException) as raised:
                await stop_daemon()
        finally:
            server.close()
            await server.wait_closed()

        assert raised.value.message.startswith(
            f"could not reach the daemon on {socket_path}: PermissionError("
        )

    # The stub takes the stop and goes on listening, which is what a daemon
    # wedged on its way out looks like from here.
    @staticmethod
    async def test_stop_says_so_when_the_daemon_keeps_answering(
        socket_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr("vekna.inits.daemon._POLLS", 3)
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
        monkeypatch.setattr("vekna.inits.daemon._KEPT", 1)
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


@pytest.mark.asyncio
class TestLeftBehind:
    # This test's own process stands in for a cast a stopped daemon spawned.
    @staticmethod
    async def test_a_cast_still_running_from_a_stopped_daemon_is_said_held(
        socket_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ):
        mark = tmp_path / "runs" / "c1" / "spawned.json"
        mark.parent.mkdir(parents=True)
        mark.write_text(
            f'{{"cast_id":"c1","pid":{os.getpid()},"project":"p","tree":null}}'
        )

        async with _served(socket_path):
            assert await alive(socket_path)

        said = capsys.readouterr().err
        assert "holding 1 cast(s) left running until they reattach" in said
        assert mark.exists()


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
        monkeypatch.setattr("vekna.inits.daemon._POLLS", 10)
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
        monkeypatch.setattr("vekna.inits.daemon.CLI_MODULE", "vekna.no_such_module")

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


_ASKER = textwrap.dedent("""
    from pydantic import BaseModel

    from vekna.folio.flow import decide
    from vekna.lexicon import Done, NoComponents, ritual, step


    class Ask(BaseModel):
        pass


    @step
    async def ask(_: Ask) -> Done[None]:
        await decide("merge #74 now?")
        return Done(None)


    @ritual("asker")
    async def asker(_: NoComponents) -> Ask:
        return Ask()
    """)
# A spawned cast is a fresh interpreter importing pydantic and the lexicon.
_SPAWN_PATIENCE = 3000


async def _spawned(ready: Callable[[], bool]) -> None:
    for _ in range(_SPAWN_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_SPAWN_PATIENCE * _TICK:.0f}s waiting for a spawned cast"
    raise AssertionError(msg)


@pytest.fixture(name="rituals")
def _rituals(socket_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = socket_path.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(project / "config"))
    (project / "rituals.py").write_text(_ASKER)
    return project


@pytest.mark.asyncio
class TestSpawning:
    @staticmethod
    async def test_c_starts_a_ritual_and_a_answers_it_from_the_view(
        socket_path: Path, rituals: Path
    ):
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c asker")
            await _spawned(lambda: keys.painted("merge #74 now?"))
            keys.press("1")
            await _eventually(lambda: keys.painted("a yes|no"))
            keys.press("a yes")
            keys.press("b")
            await _spawned(lambda: keys.showing("1 done"))
            keys.press("q")
            await peer

        [run] = Journal(rituals / "runs").recent(limit=5)
        assert not isinstance(run, DamagedRun)
        assert run.status == "ok"
        assert run.hello.ritual == "asker"
        assert run.hello.resumed_from is None
        assert run.hello.wired

    @staticmethod
    async def test_a_ritual_that_is_not_there_fails_saying_so(
        socket_path: Path, rituals: Path
    ):
        del rituals
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c nothing")
            await _spawned(lambda: keys.painted("1 failed"))
            keys.press("1")
            await _eventually(lambda: keys.painted("no ritual named 'nothing'"))
            keys.press("q")
            await peer

    @staticmethod
    async def test_past_the_project_s_processes_a_cast_waits_queued(
        socket_path: Path, rituals: Path
    ):
        (rituals / ".vekna.toml").write_text("[circle]\nprocesses = 1\n")
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c asker")
            await _spawned(lambda: keys.painted("merge #74 now?"))
            keys.press("c asker")
            await _eventually(lambda: keys.painted("1 waiting · 1 queued"))
            keys.press("1")
            await _eventually(lambda: keys.painted("a yes|no"))
            keys.press("a no")
            keys.press("b")
            # The first one done frees its slot, and the second asks in turn.
            await _spawned(lambda: keys.painted("1 waiting · 1 done"))
            keys.press("q")
            await peer

    @staticmethod
    async def test_a_request_that_cannot_be_queued_is_refused_and_logged(
        socket_path: Path,
        rituals: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        del rituals

        async def undecodable(_: Path) -> str:
            return await asyncio.to_thread(b"\xff".decode)

        monkeypatch.setattr("vekna.inits.daemon.project_of", undecodable)
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c asker")
            await _eventually(lambda: keys.painted("could not queue asker"))
            keys.press("q")
            await peer

        assert "could not queue asker" in capsys.readouterr().err

    @staticmethod
    async def test_a_tree_that_is_not_there_is_refused(
        socket_path: Path, tmp_path: Path
    ):
        nowhere = tmp_path / "nowhere"
        async with _served(socket_path):
            reader, writer = await attach(socket_path)
            writer.write(encode_frame(SurfaceHello()))
            writer.write(
                encode_frame(
                    CastRequested(
                        project_root=str(nowhere), ritual="asker", components={}
                    )
                )
            )
            await writer.drain()

            # What else a surface is told on the way is not this test's.
            async with asyncio.timeout(5):
                refused = None
                async for frame in read_frames(reader):
                    if isinstance(frame, CastRefused):
                        refused = frame
                        break
            writer.close()

        assert refused == CastRefused(reason=f"{nowhere} is not a directory")


@pytest.mark.asyncio
class TestCodingSlots:
    @staticmethod
    async def test_a_slot_past_the_limit_waits_for_the_one_released(
        socket_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        (tmp_path / "config" / "vekna").mkdir(parents=True)
        (tmp_path / "config" / "vekna" / "config.toml").write_text(
            "[circle]\ncoding = 1\n"
        )
        async with _served(socket_path):
            reader, writer = await attach(socket_path)
            frames = aiter(read_frames(reader))
            for message in (
                _hello(),
                CodingSlotRequested(cast_id="c1", request_id="s1"),
                CodingSlotRequested(cast_id="c1", request_id="s2"),
            ):
                writer.write(encode_frame(message))
            await writer.drain()

            async with asyncio.timeout(5):
                first = await anext(frames)
                writer.write(
                    encode_frame(CodingSlotReleased(cast_id="c1", request_id="s1"))
                )
                await writer.drain()
                second = await anext(frames)
            writer.close()

        assert first == CodingSlotGranted(cast_id="c1", request_id="s1")
        assert second == CodingSlotGranted(cast_id="c1", request_id="s2")


_TREE_RITUALS = textwrap.dedent("""
    from pathlib import Path

    from pydantic import BaseModel

    from vekna.lexicon import Done, NoComponents, ritual, step


    class Touch(BaseModel):
        pass


    @step
    async def touch(_: Touch) -> Done[None]:
        (Path.cwd() / "left.txt").write_text("mine")
        return Done(None)


    @ritual("tidy", worktree=True)
    async def tidy(_: NoComponents) -> Done[None]:
        return Done(None)


    @ritual("messy", worktree=True)
    async def messy(_: NoComponents) -> Touch:
        return Touch()
    """)


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=v", "-c", "user.email=v@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


# A pool tree holds only what git tracks, so the rituals are committed.
@pytest.fixture(name="repo")
def _repo(socket_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = socket_path.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(project / "config"))
    (project / "rituals.py").write_text(_TREE_RITUALS)
    (project / ".gitignore").write_text("runs/\nstate/\nconfig/\nvekna.sock*\n")
    _git(project, "init", "-q", "-b", "main")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "rituals")
    return project


def _pool_tree(repo: Path) -> Path:
    [tree] = (repo / "state" / "vekna" / "worktrees").glob("*/1")
    return tree


@pytest.mark.asyncio
class TestWorktrees:
    @staticmethod
    async def test_a_worktree_ritual_runs_in_a_pool_tree_parked_after(repo: Path):
        keys = _Keys()
        async with _served(repo / "vekna.sock"):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c tidy")
            await _spawned(lambda: keys.showing("1 done"))
            keys.press("q")
            await peer

        tree = _pool_tree(repo)
        [run] = Journal(repo / "runs").recent(limit=5)
        assert not isinstance(run, DamagedRun)
        assert run.status == "ok"
        assert Path(run.hello.project_root) == tree.resolve()
        assert _git(tree, "branch", "--show-current") == "vekna/wt-1"

    @staticmethod
    async def test_a_tree_left_dirty_is_blocked_and_said(
        repo: Path, capsys: pytest.CaptureFixture[str]
    ):
        keys = _Keys()
        async with _served(repo / "vekna.sock"):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c messy")
            await _spawned(lambda: keys.showing("1 done"))
            keys.press("1")
            await _spawned(lambda: keys.painted("left blocked: uncommitted changes"))
            keys.press("q")
            await peer

        assert (_pool_tree(repo) / "left.txt").read_text() == "mine"
        assert "is blocked after cast" in capsys.readouterr().err


_QUEUE_RITUALS = textwrap.dedent("""
    import asyncio
    from pathlib import Path

    from pydantic import BaseModel

    from vekna.folio.flow import await_cast, enqueue
    from vekna.lexicon import Done, NoComponents, ritual, step


    class Count(BaseModel):
        n: int


    class Counted(BaseModel):
        n: int


    class Sweep(BaseModel):
        pass


    @ritual("count")
    async def count(components: Count) -> Done[Counted]:
        return Done(Counted(n=components.n))


    @step
    async def sweep(_: Sweep) -> Done[Counted]:
        return Done(await await_cast("count", Count(n=3), output=Counted))


    @ritual("sweep")
    async def sweeper(_: NoComponents) -> Sweep:
        return Sweep()


    class Fan(BaseModel):
        pass


    @step
    async def fan_out(_: Fan) -> Done[Fan]:
        await enqueue("count", Count(n=1))
        return Done(Fan())


    @ritual("fan")
    async def fan(_: NoComponents) -> Fan:
        return Fan()


    class Held(BaseModel):
        pass


    # Runs until the test lets it go by touching `release` where it runs.
    @step
    async def held(_: Held) -> Done[Held]:
        while not Path("release").exists():
            await asyncio.sleep(0.05)
        return Done(Held())


    @ritual("hold")
    async def hold(_: NoComponents) -> Held:
        return Held()


    class Holding(BaseModel):
        pass


    @step
    async def holding(_: Holding) -> Done[Holding]:
        await enqueue("hold", NoComponents())
        return Done(Holding())


    @ritual("hold_one")
    async def hold_one(_: NoComponents) -> Holding:
        return Holding()
    """)


def _finished(runs: Path, ritual: str) -> bool:
    return any(
        not isinstance(run, DamagedRun)
        and run.hello.ritual == ritual
        and run.status not in {"queued", "running"}
        for run in Journal(runs).recent(limit=10)
    )


def _run_of(runs: Path, ritual: str) -> RunRecord:
    [found] = [
        run
        for run in Journal(runs).recent(limit=10)
        if not isinstance(run, DamagedRun) and run.hello.ritual == ritual
    ]
    return found


async def _hand_cast(cwd: Path, *args: str) -> tuple[list[str], int | None]:
    cast = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        CLI_MODULE,
        "cast",
        *args,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    said, _ = await asyncio.wait_for(cast.communicate(), timeout=60)
    return said.decode().splitlines(), cast.returncode


@pytest.fixture(name="queue_rituals")
def _queue_rituals(socket_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = socket_path.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(project / "config"))
    (project / "rituals.py").write_text(_QUEUE_RITUALS)
    return project


@pytest.mark.asyncio
class TestQueue:
    # Typed by hand, a cast that queues another stays for it: what the child
    # does prints under its name, and the cast ends once the child has.
    @staticmethod
    async def test_a_hand_cast_follows_what_it_queued_until_it_ends(
        socket_path: Path, queue_rituals: Path
    ):
        async with _served(socket_path):
            lines, code = await _hand_cast(queue_rituals, "fan")

        done = [line for line in lines if line.startswith("[count ")]
        assert code == 0
        assert done[-1].endswith("✓ done")
        assert lines.index("result: {}") < lines.index(done[-1])

    @staticmethod
    async def test_no_follow_ends_with_its_own_steps(
        socket_path: Path, queue_rituals: Path
    ):
        async with _served(socket_path):
            lines, code = await _hand_cast(queue_rituals, "--no-follow", "fan")
            await _spawned(lambda: _finished(queue_rituals / "runs", "count"))

        assert code == 0
        assert not [line for line in lines if line.startswith("[count ")]

    # One slot: the sweep gives it up to the child it awaits, or neither runs.
    @staticmethod
    async def test_an_awaited_child_runs_in_the_slot_its_parent_gave_up(
        socket_path: Path, queue_rituals: Path
    ):
        (queue_rituals / ".vekna.toml").write_text("[circle]\nprocesses = 1\n")
        runs = queue_rituals / "runs"
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            keys.press("c sweep")
            await _spawned(lambda: _finished(runs, "sweep"))
            keys.press("q")
            await peer

        sweep, count = _run_of(runs, "sweep"), _run_of(runs, "count")
        assert (sweep.status, sweep.result) == ("ok", {"n": 3})
        assert (count.status, count.result) == ("ok", {"n": 3})
        assert count.hello.enqueued_by == sweep.hello.cast_id
        assert count.hello.components == {"n": 3}

    # What a stopped daemon left queued, the next one runs.
    @staticmethod
    async def test_a_cast_left_queued_is_run_by_the_next_daemon(
        socket_path: Path, queue_rituals: Path
    ):
        runs = queue_rituals / "runs"
        journal = Journal(runs)
        journal.record(
            CastHello(
                cast_id="left",
                project_root=str(queue_rituals),
                project=str(queue_rituals),
                ritual="count",
                components={"n": 5},
                started_at=_WHEN,
                wired=True,
            )
        )
        journal.record(CastQueued(cast_id="left"))

        async with _served(socket_path):
            await _spawned(lambda: _finished(runs, "count"))

        left = _run_of(runs, "count")
        assert (left.status, left.result) == ("ok", {"n": 5})

    # Queued when the daemon stopped, spawned before it did: the process is the
    # one to finish it, so the next daemon does not start it twice. The fresh
    # one queued after it is what says the queue has been run.
    @staticmethod
    async def test_a_cast_left_queued_but_already_spawned_is_not_run_again(
        socket_path: Path, queue_rituals: Path
    ):
        runs = queue_rituals / "runs"
        journal = Journal(runs)
        for index, (cast_id, ritual) in enumerate(
            (("held", "nap"), ("fresh", "count"))
        ):
            journal.record(
                CastHello(
                    cast_id=cast_id,
                    project_root=str(queue_rituals),
                    project=str(queue_rituals),
                    ritual=ritual,
                    components={"n": 5},
                    started_at=_WHEN + timedelta(minutes=index),
                    wired=True,
                )
            )
            journal.record(CastQueued(cast_id=cast_id))
        mark = runs / "held" / "spawned.json"
        spawned = (
            f'{{"cast_id":"held","pid":{os.getpid()},'
            f'"project":"{queue_rituals}","tree":null}}'
        )
        mark.write_text(spawned)

        async with _served(socket_path):
            await _spawned(lambda: _finished(runs, "count"))

        assert _run_of(runs, "nap").status == "queued"
        assert mark.read_text() == spawned

    @staticmethod
    async def test_an_enqueue_naming_no_tree_is_refused(socket_path: Path):
        child = _hello("c2")
        async with _served(socket_path):
            reader, writer = await attach(socket_path)
            frames = aiter(read_frames(reader))
            for message in (
                _hello(),
                EnqueueRequested(cast_id="c1", request_id="q1", hello=child),
            ):
                writer.write(encode_frame(message))
            await writer.drain()
            async with asyncio.timeout(5):
                answer = await anext(frames)
            writer.close()

        assert answer == EnqueueRefused(
            cast_id="c1",
            request_id="q1",
            reason="/home/someone/proj is not a directory",
        )

    # Whatever the enqueue raises, the asking cast is answered rather than left
    # waiting for a reply that never comes.
    @staticmethod
    async def test_an_enqueue_that_raises_is_refused_and_logged(
        socket_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ):
        child = _hello("c2")
        denied = PermissionError(13, "Permission denied", child.project_root)
        is_dir = Path.is_dir

        def unreadable(path: Path) -> bool:
            if str(path) == child.project_root:
                raise denied
            return is_dir(path)

        monkeypatch.setattr(Path, "is_dir", unreadable)
        async with _served(socket_path):
            reader, writer = await attach(socket_path)
            frames = aiter(read_frames(reader))
            for message in (
                _hello(),
                EnqueueRequested(cast_id="c1", request_id="q1", hello=child),
            ):
                writer.write(encode_frame(message))
            await writer.drain()
            async with asyncio.timeout(5):
                answer = await anext(frames)
            writer.close()

        reason = f"could not queue {child.ritual}: {denied}"
        assert answer == EnqueueRefused(cast_id="c1", request_id="q1", reason=reason)
        assert reason in capsys.readouterr().err

    @staticmethod
    async def test_a_withdrawn_await_shows_the_cast_running_again(socket_path: Path):
        keys = _Keys()
        async with _served(socket_path):
            peer = asyncio.create_task(window(screen=keys))
            writer = await _say(
                socket_path,
                _hello(),
                AwaitRequested(cast_id="c1", request_id="w1", child="c1"),
            )
            await _eventually(lambda: keys.painted("on c1"))

            writer.write(encode_frame(AwaitWithdrawn(cast_id="c1", request_id="w1")))
            await writer.drain()

            await _eventually(lambda: keys.showing("1 running"))
            writer.close()
            keys.press("q")
            await peer


# The hand cast in this process, so what it does once its own steps end is
# measured: a subprocess's lines are not.
@pytest.mark.asyncio
class TestFollowing:
    @staticmethod
    async def test_it_says_it_is_following_and_ends_with_the_child(
        socket_path: Path, queue_rituals: Path, capsys: pytest.CaptureFixture[str]
    ):
        (queue_rituals / "release").touch()
        async with _served(socket_path):
            code = await _drive(["hold_one"])

        assert code == 0
        assert _FOLLOWING in capsys.readouterr().out

    @staticmethod
    async def test_ctrl_c_leaves_the_child_running_and_keeps_the_cast_s_code(
        socket_path: Path, queue_rituals: Path, capsys: pytest.CaptureFixture[str]
    ):
        said: list[str] = []
        async with _served(socket_path):
            cast = asyncio.create_task(_drive(["hold_one"]))
            await _spawned(lambda: _FOLLOWING in _drained(capsys, said))

            cast.cancel()
            code = await cast
            (queue_rituals / "release").touch()
            await _spawned(lambda: _finished(queue_rituals / "runs", "hold"))

        assert code == 0
        assert _LEFT in _drained(capsys, said)

    @staticmethod
    async def test_a_daemon_gone_before_the_child_ends_fails_the_cast(
        socket_path: Path, queue_rituals: Path, capsys: pytest.CaptureFixture[str]
    ):
        said: list[str] = []
        async with _served(socket_path):
            cast = asyncio.create_task(_drive(["hold_one"]))
            await _spawned(lambda: _FOLLOWING in _drained(capsys, said))

        code = await asyncio.wait_for(cast, timeout=10)
        [child] = Spawner(command=[], runs=queue_rituals / "runs").left_behind()
        (queue_rituals / "release").touch()
        # Reaped while this loop still runs, or its watcher reports to a closed one.
        await _spawned(lambda: not pid_alive(child.pid))

        assert code == 1
        assert _DAEMON_WENT in capsys.readouterr().err


def _drained(capsys: pytest.CaptureFixture[str], said: list[str]) -> str:
    said.append(capsys.readouterr().out)
    return "".join(said)
