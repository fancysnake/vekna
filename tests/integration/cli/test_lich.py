import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import click
import pytest

from vekna.inits.cli import daemon, dismiss_lich, list_liches, raise_lich
from vekna.links.registry import LichRegistry
from vekna.links.spawn import raise_detached
from vekna.pacts.lich import Phylactery
from vekna.pacts.screen import Screen

_WHEN = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_PATIENCE = 400
_TICK = 0.01
_CLI = "vekna.inits.cli"
_TWO = 2


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
