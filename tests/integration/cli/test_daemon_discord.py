import asyncio
import contextlib
import logging
import sys
import textwrap
from collections.abc import AsyncGenerator, Callable, Sequence
from pathlib import Path
from unittest.mock import AsyncMock

import discord
import pytest
from typing_extensions import override

from tests.conftest import end_spawned_casts
from vekna.inits.daemon import serve_daemon, stop_daemon
from vekna.links.journal import Journal
from vekna.links.socket_server import alive
from vekna.pacts.casts import DamagedRun
from vekna.pacts.remote import DiscordSetup, Hear, Heard, Posted, Remote
from vekna.wire import RunRecord

_PATIENCE = 400
_TICK = 0.01
# A spawned cast is a fresh interpreter importing pydantic and the lexicon.
_SPAWN_PATIENCE = 3000

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


async def _eventually(ready: Callable[[], bool]) -> None:
    for _ in range(_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_PATIENCE * _TICK:.1f}s waiting for the view to catch up"
    raise AssertionError(msg)


async def _spawned(ready: Callable[[], bool]) -> None:
    for _ in range(_SPAWN_PATIENCE):
        if ready():
            return
        await asyncio.sleep(_TICK)
    msg = f"gave up after {_SPAWN_PATIENCE * _TICK:.0f}s waiting for a spawned cast"
    raise AssertionError(msg)


# The daemon in this process, headless, and stopped the way `vekna stop` does
# it — which is also what proves it was still up after every test.
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
        await end_spawned_casts(socket_path.parent / "runs")


@pytest.fixture(name="socket_path")
def _socket_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VEKNA_SOCKET", str(tmp_path / "vekna.sock"))
    monkeypatch.setenv("VEKNA_RUNS", str(tmp_path / "runs"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "vekna.sock"


@pytest.fixture(name="rituals")
def _rituals(socket_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = socket_path.parent
    monkeypatch.setenv("XDG_CONFIG_HOME", str(project / "config"))
    (project / "rituals.py").write_text(_ASKER)
    return project


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


def _said(caplog: pytest.LogCaptureFixture, level: int) -> str:
    return "\n".join(
        record.getMessage() for record in caplog.records if record.levelno == level
    )


_OPERATOR = 7
_GUILD = 100


# Discord, as the daemon reaches it: what makes the remote, and the remote.
class _Chat(Remote):
    def __init__(self, *, ends: bool = False) -> None:
        self.ends = ends
        self.setups: list[DiscordSetup] = []
        self.asked: list[tuple[str, str, str]] = []
        self.offered: list[tuple[str, ...]] = []
        self.said: list[tuple[str, str]] = []
        self.hear: Hear | None = None
        self.closed = False

    def remote(self, setup: DiscordSetup) -> Remote:
        self.setups.append(setup)
        return self

    @override
    async def ask(
        self, *, room: str, thread: str, text: str, reactions: Sequence[str] = ()
    ) -> Posted:
        self.asked.append((room, thread, text))
        self.offered.append(tuple(reactions))
        return Posted(thread="t1", message="m1")

    @override
    async def say(self, *, thread: str, text: str) -> None:
        self.said.append((thread, text))

    @override
    async def run(self, hear: Hear) -> None:
        self.hear = hear
        try:
            if not self.ends:
                await asyncio.Event().wait()
        finally:
            self.closed = True


# A daemon with a `[discord]` and its token, in a project its user config
# lists.
@pytest.fixture(name="discord_config")
def _discord_config(rituals: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("vekna.inits.daemon._VIGIL_SECONDS", _TICK)
    monkeypatch.setattr("vekna.inits.daemon._DISCORD_SECONDS", _TICK)
    (rituals / "config" / "vekna").mkdir(parents=True)
    config = rituals / "config" / "vekna" / "config.toml"
    config.write_text(
        f'[projects.here]\npath = "{rituals}"\n'
        f"[discord]\nguild = {_GUILD}\nallow = [{_OPERATOR}]\n",
        encoding="utf-8",
    )
    config.with_name("discord-token").write_text("s3cret\n", encoding="utf-8")
    return config


# Each time a surface attached or detached, as `--debug` wrote it down.
def _surfaces(log: Path) -> list[str]:
    return [
        line.partition(" - surface_hello ")[2]
        for line in log.read_text(encoding="utf-8").splitlines()
        if " - surface_hello " in line
    ]


def _edit(config: Path, *, old: str, new: str) -> None:
    listed = config.read_text(encoding="utf-8")
    config.write_text(listed.replace(old, new), encoding="utf-8")


def _keep_asking(config: Path) -> None:
    listed = config.read_text(encoding="utf-8")
    config.write_text(
        listed + '[vigil.asking]\nevery = 3600\nritual = "asker"\n', encoding="utf-8"
    )


@pytest.mark.asyncio
class TestDiscord:
    @staticmethod
    async def test_a_vigil_casts_question_is_answered_from_its_thread(
        socket_path: Path,
        discord_config: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        chat = _Chat()
        monkeypatch.setattr("vekna.links.discord.DiscordRemote", chat.remote)
        runs = socket_path.parent / "runs"
        _keep_asking(discord_config)
        async with _served(socket_path):
            await _spawned(lambda: bool(chat.asked))
            assert chat.hear is not None
            refused = await chat.hear(Heard(thread="t1", reply_to=None, text="maybe"))
            taken = await chat.hear(Heard(thread="t1", reply_to=None, text="Yes"))
            await _spawned(lambda: _finished(runs, "asker"))
            await _eventually(lambda: bool(chat.said))

        asker = _run_of(runs, "asker")
        assert (asker.status, asker.hello.vigil) == ("ok", "asking")
        assert chat.setups == [
            DiscordSetup(
                token="s3cret",
                guild=_GUILD,
                category="vekna",
                allow=frozenset({_OPERATOR}),
            )
        ]
        assert chat.asked == [
            (
                discord_config.parents[2].name,
                "asker",
                (
                    f"❓ **asker** `{asker.hello.cast_id[:8]}` asks\n"
                    "merge #74 now?\n💬 _reply yes or no_"
                ),
            )
        ]
        assert chat.offered == [("👍", "❌")]
        assert (refused, taken) == ("'maybe' is not one of yes, no", None)
        assert chat.said == [("t1", "✅ ACK")]
        assert chat.closed
        assert (
            f"answering casts on Discord, in the guild {_GUILD}" in _said(
                caplog, logging.INFO
            ).splitlines()
        )
        assert not _said(caplog, logging.ERROR)

    @staticmethod
    async def test_an_edited_discord_table_moves_the_relay_to_the_new_setup(
        socket_path: Path,
        discord_config: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        chat = _Chat()
        monkeypatch.setattr("vekna.links.discord.DiscordRemote", chat.remote)
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log):
            await _eventually(lambda: bool(chat.setups))
            _edit(discord_config, old=f"guild = {_GUILD}", new="guild = 200")
            await _eventually(lambda: bool(chat.setups[1:]))
            plugged = _surfaces(log)

        assert [setup.guild for setup in chat.setups] == [_GUILD, 200]
        assert plugged == ["attached", "detached", "attached"]
        assert [
            line
            for line in _said(caplog, logging.INFO).splitlines()
            if "on Discord" in line
        ] == [
            f"answering casts on Discord, in the guild {_GUILD}",
            "no longer answering casts on Discord: its config changed",
            "answering casts on Discord, in the guild 200",
        ]
        assert not _said(caplog, logging.WARNING)
        assert not _said(caplog, logging.ERROR)

    @staticmethod
    async def test_a_relay_that_ended_is_started_again_by_an_edit(
        socket_path: Path,
        discord_config: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        chat = _Chat(ends=True)
        monkeypatch.setattr("vekna.links.discord.DiscordRemote", chat.remote)
        async with _served(socket_path):
            await _eventually(lambda: bool(_said(caplog, logging.ERROR)))
            _edit(discord_config, old=f"guild = {_GUILD}", new="guild = 200")
            await _eventually(lambda: bool(chat.setups[1:]))

        assert [setup.guild for setup in chat.setups] == [_GUILD, 200]
        assert [
            line
            for line in _said(caplog, logging.INFO).splitlines()
            if "on Discord" in line
        ] == [
            f"answering casts on Discord, in the guild {_GUILD}",
            "answering casts on Discord, in the guild 200",
        ]

    @staticmethod
    async def test_a_discord_table_taken_away_unplugs_the_relay(
        socket_path: Path,
        discord_config: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        caplog.set_level(logging.INFO)
        chat = _Chat()
        monkeypatch.setattr("vekna.links.discord.DiscordRemote", chat.remote)
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log):
            await _eventually(lambda: bool(chat.setups))
            _edit(
                discord_config,
                old=f"[discord]\nguild = {_GUILD}\nallow = [{_OPERATOR}]\n",
                new="",
            )
            await _eventually(lambda: log.exists() and "detached" in _surfaces(log))
            assert await alive(socket_path)

        assert _surfaces(log) == ["attached", "detached"]
        assert len(chat.setups) == 1
        assert (
            "no longer answering casts on Discord: its config changed" in _said(
                caplog, logging.INFO
            ).splitlines()
        )
        assert not _said(caplog, logging.ERROR)

    @staticmethod
    @pytest.mark.usefixtures("discord_config")
    async def test_without_the_install_it_is_said_once_and_the_daemon_serves(
        socket_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        monkeypatch.delitem(sys.modules, "vekna.links.discord", raising=False)
        monkeypatch.setitem(sys.modules, "discord", None)
        async with _served(socket_path):
            assert await alive(socket_path)

        assert _said(caplog, logging.WARNING).splitlines() == [
            "Discord is off: install vekna[discord] to answer casts there"
        ]

    @staticmethod
    @pytest.mark.usefixtures("discord_config")
    async def test_a_connection_that_ends_unplugs_the_relay_and_is_said(
        socket_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        chat = _Chat(ends=True)
        monkeypatch.setattr("vekna.links.discord.DiscordRemote", chat.remote)
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log):
            await _eventually(lambda: bool(_said(caplog, logging.ERROR)))
            unplugged = _surfaces(log)

        assert unplugged == ["attached", "detached"]
        assert chat.closed
        assert _said(caplog, logging.ERROR).splitlines() == [
            (
                "Discord is off until its config changes or the daemon restarts:"
                " RemoteError('the connection ended')"
            )
        ]

    @staticmethod
    @pytest.mark.usefixtures("discord_config")
    async def test_a_token_discord_refuses_is_said_and_the_daemon_serves(
        socket_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        start = AsyncMock(
            side_effect=discord.LoginFailure("Improper token has been passed.")
        )
        monkeypatch.setattr(discord.Client, "start", start)
        log = socket_path.parent / "debug.log"
        async with _served(socket_path, debug=log):
            await _eventually(lambda: bool(_said(caplog, logging.ERROR)))
            assert await alive(socket_path)
            unplugged = _surfaces(log)

        assert unplugged == ["attached", "detached"]
        start.assert_awaited_once_with("s3cret")
        assert _said(caplog, logging.ERROR).splitlines() == [
            (
                "Discord is off until its config changes or the daemon restarts:"
                " RemoteError('Improper token has been passed.')"
            )
        ]
