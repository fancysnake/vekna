import asyncio
import contextlib
import os
import signal
import sys
import textwrap
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import click
import pytest

from vekna.inits.cli import attach_lich, daemon, dismiss_lich, list_liches, raise_lich
from vekna.links.registry import LichRegistry
from vekna.links.socket_server import attach
from vekna.links.spawn import raise_detached
from vekna.pacts.lich import Phylactery
from vekna.pacts.screen import Screen
from vekna.wire import (
    CastHello,
    CastKillRequested,
    CastRefused,
    CastRequested,
    LichStatus,
    SurfaceHello,
    WireMessage,
    encode_frame,
    read_frames,
)

_MessageT = TypeVar("_MessageT", bound=WireMessage)

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 400
_TICK = 0.01
_CLI = "vekna.inits.cli"
_TWO = 2
_SLOW_PATIENCE = 3000


# The daemon's own terminal, and — where a lich is being raised — the one the
# raising prompt asks at. `read_line` hands back what the test queued, and None
# once it has run out, which is a closed stdin.
class _Keys(Screen):
    def __init__(self, *typed: str) -> None:
        self.frames: list[str] = []
        self._typed = list(typed)

    def show(self, screen: str) -> None:
        self.frames.append(screen)

    async def read_line(self) -> str | None:
        return self._typed.pop(0) if self._typed else None

    def painted(self, text: str) -> bool:
        return any(text in frame for frame in self.frames)


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s waiting for the lich"
    raise AssertionError(msg)


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    # A lich is raised in a project directory and rooted there, so "here" is
    # this test's own directory rather than whatever the suite was started in.
    monkeypatch.chdir(tmp_path)
    return tmp_path / "vekna.sock"


@pytest.fixture(name="state")
def _state(tmp_path: Path, socket_path: Path) -> Path:
    del socket_path
    return tmp_path / "state" / "vekna"


# The daemon on this test's own loop: a lich command is asynchronous all the way
# down and the socket is the only thing between the two.
@contextlib.asynccontextmanager
async def _daemon_at(socket_path: Path) -> AsyncIterator[_Keys]:
    screen = _Keys()
    running = asyncio.create_task(daemon(screen=screen))
    await _eventually(socket_path.exists)
    try:
        yield screen
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


def _rows(state: Path) -> list[Phylactery]:
    return LichRegistry(state).rows()


def _names(state: Path) -> list[str]:
    return [row.name for row in _rows(state)]


def _keep(state: Path, name: str, *, root: str) -> None:
    LichRegistry(state).save(Phylactery(name=name, root=root, created=_WHEN))


# What `vekna liches` prints, now. Liveness is the daemon holding a socket, so
# asking it is the only way to know — which is what this command does.
async def _listed(capsys: pytest.CaptureFixture[str]) -> str:
    capsys.readouterr()
    await list_liches()
    return capsys.readouterr().out


@pytest.mark.asyncio
class TestRaising:
    @staticmethod
    async def test_a_lich_stands_named_and_idle(
        socket_path: Path, state: Path, capsys: pytest.CaptureFixture[str]
    ):
        async with _daemon_at(socket_path):
            assert await raise_lich(named="hollow-vesper", fresh=False) == 0
            # The row is written by the daemon when the lich reports itself, so
            # a row is the lich standing rather than the spawn returning.
            await _eventually(lambda: _names(state) == ["hollow-vesper"])

            listed = await _listed(capsys)

        assert "hollow-vesper" in listed
        assert "idle" in listed

    @staticmethod
    async def test_a_fresh_lich_is_named_for_itself(socket_path: Path, state: Path):
        async with _daemon_at(socket_path):
            await raise_lich(named=None, fresh=True)

            await _eventually(lambda: len(_names(state)) == 1)

        assert "-" in _names(state)[0]

    # The row is the lich. Kill the process and it is dormant, not gone — which
    # is what lets `vekna lich` offer it again afterwards.
    @staticmethod
    async def test_a_killed_lich_leaves_its_row_behind(
        socket_path: Path,
        state: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ):
        here = str(tmp_path)
        async with _daemon_at(socket_path):
            # Spawned by hand rather than through `raise_lich`, because what
            # this is about is the process dying and only the spawn knows its
            # pid.
            pid = await raise_detached(
                argv=[
                    sys.executable,
                    "-m",
                    _CLI,
                    "lich",
                    "--serve",
                    "ashen-quill",
                    here,
                ],
                cwd=here,
            )
            await _eventually(lambda: _names(state) == ["ashen-quill"])

            os.kill(pid, signal.SIGTERM)
            await _until_listed(capsys, "dormant")

        assert _names(state) == ["ashen-quill"]

    @staticmethod
    async def test_a_lich_already_standing_is_not_raised_twice(
        socket_path: Path, state: Path
    ):
        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))

            with pytest.raises(click.ClickException, match="already standing"):
                await raise_lich(named="hollow-vesper", fresh=False)

    # `--name` from an unrelated directory raises that lich in its own root,
    # which is the thing its row is remembered for.
    @staticmethod
    async def test_a_named_lich_stands_in_its_own_root(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        _keep(state, "ashen-quill", root=str(elsewhere))

        async with _daemon_at(socket_path):
            await raise_lich(named="ashen-quill", fresh=False)
            await _eventually(lambda: bool(_names(state)))

        assert _rows(state)[0].root == str(elsewhere)

    # A row outlives the directory it names, and a project deleted between two
    # raisings is the likeliest thing to have gone wrong.
    @staticmethod
    async def test_a_lich_whose_root_is_gone_says_so(socket_path: Path, state: Path):
        _keep(state, "ashen-quill", root="/not-a-directory")

        async with _daemon_at(socket_path):
            with pytest.raises(click.ClickException, match="is not there any more"):
                await raise_lich(named="ashen-quill", fresh=False)


@pytest.mark.asyncio
class TestTheRaisingPrompt:
    @staticmethod
    async def test_a_sleeping_lich_here_is_offered_and_can_be_revived(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        _keep(state, "ashen-quill", root=str(tmp_path))
        keys = _Keys("1")

        async with _daemon_at(socket_path):
            await raise_lich(named=None, fresh=False, screen=keys)
            await _eventually(lambda: len(_names(state)) == 1)

        assert keys.painted("One lich sleeps here.")
        assert keys.painted("ashen-quill")

    # Enter, or no stdin at all, takes what the prompt offers last: a new one.
    # Nothing is revived by accident, which is the half that cannot be undone.
    @staticmethod
    async def test_saying_nothing_raises_a_new_one(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        _keep(state, "ashen-quill", root=str(tmp_path))

        async with _daemon_at(socket_path):
            await raise_lich(named=None, fresh=False, screen=_Keys())

            await _eventually(lambda: len(_names(state)) == _TWO)

    # An answer that names nothing raises nothing: the operator meant one of
    # those and mistyped, and drawing a fresh lich instead is not what they
    # asked for.
    @staticmethod
    async def test_an_answer_that_names_nothing_raises_nothing(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        _keep(state, "ashen-quill", root=str(tmp_path))

        async with _daemon_at(socket_path):
            with pytest.raises(click.ClickException, match="is not one of those"):
                await raise_lich(named=None, fresh=False, screen=_Keys("wat"))

        assert _names(state) == ["ashen-quill"]

    @staticmethod
    async def test_a_sleeper_can_be_answered_by_name(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        _keep(state, "ashen-quill", root=str(tmp_path))

        async with _daemon_at(socket_path):
            await raise_lich(named=None, fresh=False, screen=_Keys("ashen-quill"))

            await _eventually(lambda: bool(_names(state)))
        assert _names(state) == ["ashen-quill"]

    # A lich rooted somewhere else is not this directory's to carry on, so it is
    # not offered — and with nothing to offer there is no question to ask.
    @staticmethod
    async def test_a_lich_rooted_elsewhere_is_not_offered(
        socket_path: Path, state: Path
    ):
        _keep(state, "ashen-quill", root="/somewhere-else")
        keys = _Keys("1")

        async with _daemon_at(socket_path):
            await raise_lich(named=None, fresh=False, screen=keys)

            await _eventually(lambda: len(_names(state)) == _TWO)
        assert not keys.frames


@pytest.mark.asyncio
class TestDismissing:
    @staticmethod
    async def test_the_row_goes_and_the_lich_stops_standing(
        socket_path: Path, state: Path
    ):
        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))

            assert await dismiss_lich("hollow-vesper") == 0

            await _eventually(lambda: not _names(state))

    @staticmethod
    async def test_dismissing_a_lich_nobody_has_says_so(socket_path: Path):
        async with _daemon_at(socket_path):
            with pytest.raises(click.ClickException, match="no lich named"):
                await dismiss_lich("nobody")


@pytest.mark.asyncio
class TestWithoutADaemon:
    @staticmethod
    async def test_raising_a_lich_needs_one(socket_path: Path):
        del socket_path

        with pytest.raises(click.ClickException, match="no vekna is running"):
            await raise_lich(named="hollow-vesper", fresh=False)

    # The rows are on disk and readable without one; what cannot be known is
    # which of them is live, and with no daemon the answer is none of them.
    @staticmethod
    async def test_the_listing_still_shows_what_is_on_disk(
        state: Path, capsys: pytest.CaptureFixture[str]
    ):
        _keep(state, "ashen-quill", root="/proj")

        listed = await _listed(capsys)

        assert "ashen-quill" in listed
        assert "dormant" in listed


async def _until_listed(capsys: pytest.CaptureFixture[str], text: str) -> None:
    for _ in range(_PATIENCE):
        if text in await _listed(capsys):
            return
        await asyncio.sleep(_TICK)
    msg = f"the listing never said {text!r}"
    raise AssertionError(msg)


_RITUALS = textwrap.dedent("""
    import asyncio

    from pydantic import BaseModel

    from vekna.lexicon import NoComponents, Transition, done, goto, ritual, status, step


    class Tick(BaseModel):
        left: int


    class Countdown(BaseModel):
        start: int


    @step
    async def tick(state: Tick) -> Transition:
        status(f"{state.left} to go")
        if not state.left:
            return done(state)
        return goto(tick, Tick(left=state.left - 1))


    @ritual("countdown")
    async def countdown(components: Countdown) -> Transition:
        return goto(tick, Tick(left=components.start))


    @step
    async def linger(_: NoComponents) -> Transition:
        await asyncio.sleep(30)
        return done()


    @ritual("slow")
    async def slow(_: NoComponents) -> Transition:
        return goto(linger, NoComponents())
    """)


# A surface on the daemon, which is what an attached shell and a Discord channel
# both are: it hears everything and it may now speak.
class _Watcher:
    def __init__(self) -> None:
        self.heard: list[WireMessage] = []
        self._writer: asyncio.StreamWriter | None = None
        self._reading: asyncio.Task[None] | None = None

    async def attach_to(self, socket_path: Path) -> None:
        reader, self._writer = await attach(socket_path)
        self._writer.write(encode_frame(SurfaceHello()))
        self._reading = asyncio.create_task(self._listen(reader))

    def send(self, message: WireMessage) -> None:
        assert self._writer is not None
        self._writer.write(encode_frame(message))

    def of_kind(self, kind: type[_MessageT]) -> list[_MessageT]:
        return [message for message in self.heard if isinstance(message, kind)]

    async def close(self) -> None:
        if self._reading is not None:
            self._reading.cancel()
            await asyncio.gather(self._reading, return_exceptions=True)
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(OSError):
                await self._writer.wait_closed()

    async def _listen(self, reader: asyncio.StreamReader) -> None:
        async for message in read_frames(reader):
            self.heard.append(message)


def _casting(watcher: _Watcher, name: str) -> LichStatus | None:
    for message in reversed(watcher.of_kind(LichStatus)):
        if message.lich == name:
            return message
    return None


@contextlib.asynccontextmanager
async def _watching(socket_path: Path) -> AsyncIterator[_Watcher]:
    watcher = _Watcher()
    await watcher.attach_to(socket_path)
    try:
        yield watcher
    finally:
        await watcher.close()


@pytest.mark.asyncio
class TestCasting:
    @staticmethod
    async def test_a_cast_ordered_from_a_surface_runs_and_is_the_lich_s(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)

        async with _daemon_at(socket_path), _watching(socket_path) as watcher:
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))

            watcher.send(
                CastRequested(lich="hollow-vesper", argv=["countdown", "--start", "1"])
            )
            await _slowly(lambda: bool(watcher.of_kind(CastHello)))

            hello = watcher.of_kind(CastHello)[0]
            assert hello.ritual == "countdown"
            # The cast says whose it is, which is what makes a lich's history a
            # query over the journal rather than a list somebody maintains.
            assert hello.lich == "hollow-vesper"
            await _slowly(lambda: _rows(state)[0].last_cast == hello.cast_id)

    # One cast, never two — and the refusal names what is running rather than
    # leaving the operator to go and look.
    @staticmethod
    async def test_a_second_cast_is_refused_and_kill_is_the_way_out(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)

        async with _daemon_at(socket_path), _watching(socket_path) as watcher:
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))
            watcher.send(CastRequested(lich="hollow-vesper", argv=["slow"]))
            await _slowly(lambda: _running(watcher) == "slow")

            watcher.send(CastRequested(lich="hollow-vesper", argv=["countdown"]))
            await _slowly(lambda: bool(watcher.of_kind(CastRefused)))

            refused = watcher.of_kind(CastRefused)[0]
            assert (refused.lich, refused.ritual) == ("hollow-vesper", "slow")
            # And what it said to do about it works.
            watcher.send(CastKillRequested(lich="hollow-vesper"))
            await _slowly(lambda: _running(watcher) is None)


def _running(watcher: _Watcher) -> str | None:
    said = _casting(watcher, "hollow-vesper")
    return None if said is None else said.ritual


# A cast is a Python process that imports the lexicon, the folios and the user's
# rituals before it says anything, so what a lich does is slower than what the
# daemon does.
async def _slowly(ready: Callable[[], bool]) -> None:
    for _ in range(_SLOW_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_SLOW_PATIENCE * _TICK:.1f}s waiting for the cast"
    raise AssertionError(msg)


# A terminal nobody is sitting at until the test types. Reading blocks on the
# queue, which is what a real one does between keystrokes.
class _Typed(Screen):
    def __init__(self) -> None:
        self.frames: list[str] = []
        self._keys: asyncio.Queue[str | None] = asyncio.Queue()

    def show(self, screen: str) -> None:
        self.frames.append(screen)

    async def read_line(self) -> str | None:
        return await self._keys.get()

    def press(self, key: str) -> None:
        self._keys.put_nowait(key)

    def painted(self, text: str) -> bool:
        return any(text in frame for frame in self.frames)


@pytest.mark.asyncio
class TestAttaching:
    @staticmethod
    async def test_a_shell_on_the_session_orders_a_cast_and_watches_it(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)

        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))
            keys = _Typed()
            attached = asyncio.create_task(
                attach_lich(named="hollow-vesper", screen=keys)
            )
            await _eventually(lambda: keys.painted("hollow-vesper · idle"))

            keys.press("cast slow")
            await _slowly(lambda: keys.painted("casting slow"))

            # And the way out of a cast that will not end on its own.
            keys.press("kill")
            await _slowly(lambda: keys.frames[-1].startswith("hollow-vesper · idle"))
            keys.press("q")
            assert await attached == 0

    # The ritual's own line, under the lich's: the lich can say what it is
    # casting and no more, and which of eight PRs this is belongs to the author.
    @staticmethod
    async def test_the_ritual_s_own_line_shows_under_the_lich_s(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)

        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))
            keys = _Typed()
            attached = asyncio.create_task(
                attach_lich(named="hollow-vesper", screen=keys)
            )
            await _eventually(lambda: bool(keys.frames))

            keys.press("cast countdown --start=2")
            await _slowly(lambda: keys.painted("to go"))

            keys.press("q")
            assert await attached == 0

    @staticmethod
    async def test_a_second_cast_from_the_shell_is_refused_in_its_own_words(
        socket_path: Path, state: Path, tmp_path: Path
    ):
        (tmp_path / "rituals.py").write_text(_RITUALS)

        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))
            keys = _Typed()
            attached = asyncio.create_task(
                attach_lich(named="hollow-vesper", screen=keys)
            )
            await _eventually(lambda: bool(keys.frames))
            keys.press("cast slow")
            await _slowly(lambda: keys.painted("casting slow"))

            keys.press("cast countdown")
            await _slowly(lambda: keys.painted("`kill` is the way out"))

            keys.press("kill")
            keys.press("q")
            assert await attached == 0

    @staticmethod
    async def test_a_line_that_is_not_a_command_says_what_is(
        socket_path: Path, state: Path
    ):
        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))
            keys = _Typed()
            attached = asyncio.create_task(
                attach_lich(named="hollow-vesper", screen=keys)
            )
            await _eventually(lambda: bool(keys.frames))

            keys.press("dance")
            await _eventually(lambda: keys.painted("is not a command"))

            keys.press("q")
            assert await attached == 0

    @staticmethod
    async def test_attaching_to_nothing_says_so(socket_path: Path):
        async with _daemon_at(socket_path):
            with pytest.raises(click.ClickException, match="no lich is standing"):
                await attach_lich(named=None)

    @staticmethod
    async def test_attaching_to_a_name_nobody_holds_says_so(
        socket_path: Path, state: Path
    ):
        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await _eventually(lambda: bool(_names(state)))

            with pytest.raises(click.ClickException, match="is not standing"):
                await attach_lich(named="ashen-quill")

    # With no name and more than one standing, guessing is worse than asking.
    @staticmethod
    async def test_several_standing_and_no_name_says_which(
        socket_path: Path, state: Path
    ):
        async with _daemon_at(socket_path):
            await raise_lich(named="hollow-vesper", fresh=False)
            await raise_lich(named="ashen-quill", fresh=False)
            await _eventually(lambda: len(_names(state)) == _TWO)

            with pytest.raises(click.ClickException, match="say which"):
                await attach_lich(named=None)
