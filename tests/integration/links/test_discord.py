import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, call

import discord
import pytest

from vekna.links.discord import DiscordRemote, _Client, channel_name
from vekna.pacts.remote import DiscordSetup, Heard, Posted, Remote, RemoteError, Tapped

_GUILD = 100
_OPERATOR = 7
_OTHER = 9
_STRANGER = 8
_THREAD = 555
_SETUP = DiscordSetup(
    token="s3cret", guild=_GUILD, category="vekna", allow=frozenset({_OTHER, _OPERATOR})
)
_MENTIONS = "<@7> <@9>"


def _named(name: str, **attributes: object) -> MagicMock:
    found = MagicMock(**attributes)
    found.name = name
    return found


def _sent(message_id: int) -> MagicMock:
    return MagicMock(id=message_id, add_reaction=AsyncMock())


# A guild as the gateway's cache holds it once the client is ready.
class _Guild:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.thread = _named(
            "heal · c0ffee00",
            id=_THREAD,
            send=AsyncMock(side_effect=[_sent(1), _sent(2)]),
        )
        self.channel = _named(
            "app", threads=[], create_thread=AsyncMock(return_value=self.thread)
        )
        self.category = _named("vekna", text_channels=[])
        self.guild = MagicMock(
            categories=[],
            create_category=AsyncMock(return_value=self.category),
            create_text_channel=AsyncMock(return_value=self.channel),
        )
        self.asked: list[int] = []
        monkeypatch.setattr(discord.Client, "wait_until_ready", AsyncMock())
        monkeypatch.setattr(discord.Client, "get_guild", self._get)

    def _get(self, guild_id: int) -> MagicMock | None:
        self.asked.append(guild_id)
        return self.guild if guild_id == _GUILD else None

    def settled(self) -> None:
        self.guild.categories = [self.category]
        self.category.text_channels = [_named("other"), self.channel]
        self.channel.threads = [_named("heal · 00000000"), self.thread]


@pytest.fixture(name="guild")
def _guild(monkeypatch: pytest.MonkeyPatch) -> _Guild:
    return _Guild(monkeypatch)


# What a thread already holds, newest first, as Discord hands history out.
def _history(*messages: MagicMock) -> MagicMock:
    held = MagicMock()
    held.__aiter__.return_value = list(messages)
    return MagicMock(return_value=held)


def _written(content: str, *, author: int = _OPERATOR, bot: bool = False) -> MagicMock:
    return MagicMock(id=40, content=content, author=MagicMock(bot=bot, id=author))


def _message(**attributes: object) -> MagicMock:
    settings: dict[str, object] = {
        "author": MagicMock(bot=False, id=_OPERATOR),
        "guild": MagicMock(id=_GUILD),
        "channel": MagicMock(spec=discord.Thread, id=_THREAD),
        "reference": None,
        "content": "push",
        "reply": AsyncMock(),
    }
    return MagicMock(**(settings | attributes))


# The gateway, standing in for Discord: it hands the client each message once
# the client has started.
def _gateway(monkeypatch: pytest.MonkeyPatch, *messages: MagicMock) -> list[str]:
    tokens: list[str] = []

    async def start(client: _Client, token: str) -> None:
        tokens.append(token)
        for message in messages:
            await client.on_message(message)

    monkeypatch.setattr(discord.Client, "start", start)
    return tokens


def _tap(**attributes: object) -> MagicMock:
    settings: dict[str, object] = {
        "guild_id": _GUILD,
        "user_id": _OPERATOR,
        "member": MagicMock(bot=False),
        "channel_id": _THREAD,
        "message_id": 42,
        "emoji": "👍",
    }
    return MagicMock(**(settings | attributes))


# The gateway again, handing the client each reaction once it has started.
def _tapping(monkeypatch: pytest.MonkeyPatch, *taps: MagicMock) -> MagicMock:
    async def start(client: _Client, _: str) -> None:
        for tap in taps:
            await client.on_raw_reaction_add(tap)

    thread = MagicMock(send=AsyncMock())
    monkeypatch.setattr(discord.Client, "start", start)
    monkeypatch.setattr(discord.Client, "get_partial_messageable", lambda _, __: thread)
    return thread


async def _connected_for_good(_: _Client, __: str) -> None:
    await asyncio.Event().wait()


# A remote whose `run` has entered the client and stays connected.
@contextlib.asynccontextmanager
async def _connected(
    monkeypatch: pytest.MonkeyPatch, setup: DiscordSetup = _SETUP
) -> AsyncGenerator[Remote]:
    monkeypatch.setattr(discord.Client, "start", _connected_for_good)
    made = DiscordRemote(setup)
    running = asyncio.create_task(made.run(AsyncMock()))
    await asyncio.sleep(0)
    try:
        yield made
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


class TestChannelName:
    @staticmethod
    @pytest.mark.parametrize(
        ("room", "name"),
        [
            ("vekna", "vekna"),
            ("My Repo.py", "my-repo-py"),
            ("under_score-9", "under_score-9"),
            ("...", "project"),
        ],
    )
    def test_a_room_is_named_as_discord_would_rewrite_it(room: str, name: str):
        assert channel_name(room) == name


@pytest.mark.asyncio
class TestAsk:
    @staticmethod
    async def test_the_first_question_makes_the_category_the_room_and_the_thread(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        async with _connected(monkeypatch) as chat:
            posted = await chat.ask(room="App", thread="heal · c0ffee00", text="push?")

        assert posted == Posted(thread=str(_THREAD), message="1")
        assert guild.asked == [_GUILD]
        guild.guild.create_category.assert_awaited_once_with("vekna")
        guild.guild.create_text_channel.assert_awaited_once_with(
            "app", category=guild.category
        )
        guild.channel.create_thread.assert_awaited_once_with(
            name="heal · c0ffee00", type=discord.ChannelType.public_thread
        )
        guild.thread.send.assert_awaited_once_with(f"{_MENTIONS}\npush?")

    @staticmethod
    async def test_a_later_question_finds_them_by_name_and_makes_nothing(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()

        async with _connected(monkeypatch) as chat:
            await chat.ask(room="app", thread="heal · c0ffee00", text="push?")

        guild.guild.create_category.assert_not_awaited()
        guild.guild.create_text_channel.assert_not_awaited()
        guild.channel.create_thread.assert_not_awaited()
        guild.thread.send.assert_awaited_once_with(f"{_MENTIONS}\npush?")

    @staticmethod
    async def test_a_long_question_is_posted_whole_and_replied_to_by_its_end(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        first, second = "x " * 600, "y" * 800

        async with _connected(monkeypatch) as chat:
            posted = await chat.ask(
                room="app", thread="heal · c0ffee00", text=f"{first}\n{second}"
            )

        assert posted.message == "2"
        assert guild.thread.send.await_args_list == [
            call(f"{_MENTIONS}\n{first}"),
            call(second),
        ]

    @staticmethod
    async def test_the_reactions_are_put_under_the_end_of_the_question_in_order(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        first, last = _sent(1), _sent(2)
        guild.thread.send = AsyncMock(side_effect=[first, last])

        async with _connected(monkeypatch) as chat:
            await chat.ask(
                room="app",
                thread="heal · c0ffee00",
                text=f"{'x ' * 600}\n{'y' * 800}",
                reactions=("👍", "❌"),
            )

        first.add_reaction.assert_not_awaited()
        assert last.add_reaction.await_args_list == [call("👍"), call("❌")]

    @staticmethod
    async def test_a_reaction_discord_refuses_is_logged_and_the_next_is_still_put(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        guild.settled()
        message = _sent(1)
        message.add_reaction = AsyncMock(
            side_effect=[discord.DiscordException("no"), None]
        )
        guild.thread.send = AsyncMock(return_value=message)

        with caplog.at_level(logging.WARNING, logger="vekna.links.discord"):
            async with _connected(monkeypatch) as chat:
                posted = await chat.ask(
                    room="app",
                    thread="heal · c0ffee00",
                    text="push?",
                    reactions=("👍", "❌"),
                )

        assert posted == Posted(thread=str(_THREAD), message="1")
        assert message.add_reaction.await_args_list == [call("👍"), call("❌")]
        assert [record.getMessage() for record in caplog.records] == [
            "could not put 👍 under a question: no"
        ]

    @staticmethod
    async def test_a_question_still_waiting_in_its_thread_is_not_posted_again(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        guild.thread.history = _history(
            _written("later"),
            _written("not mine", author=_STRANGER),
            _written("push"),
            _written(f"{_MENTIONS}\npush?", bot=True),
            _written("older"),
        )

        async with _connected(monkeypatch) as chat:
            posted = await chat.ask(room="app", thread="heal · c0ffee00", text="push?")

        assert posted == Posted(
            thread=str(_THREAD), message="40", unheard=("push", "later")
        )
        guild.thread.send.assert_not_awaited()

    @staticmethod
    async def test_a_question_asked_after_another_post_of_the_bots_is_posted(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        guild.thread.history = _history(
            _written("push"),
            _written("✅ push", bot=True),
            _written(f"{_MENTIONS}\npush?", bot=True),
        )

        async with _connected(monkeypatch) as chat:
            posted = await chat.ask(room="app", thread="heal · c0ffee00", text="push?")

        assert posted == Posted(thread=str(_THREAD), message="1")
        guild.thread.send.assert_awaited_once_with(f"{_MENTIONS}\npush?")

    @staticmethod
    async def test_a_guild_the_bot_is_not_in_is_said(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        setup = DiscordSetup(
            token="s3cret", guild=404, category="vekna", allow=frozenset({_OPERATOR})
        )

        async with _connected(monkeypatch, setup) as chat:
            with pytest.raises(RemoteError, match="the bot is not in the guild 404"):
                await chat.ask(room="app", thread="t", text="push?")
        assert guild.asked == [404]

    @staticmethod
    async def test_what_discord_refuses_is_a_remote_error(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        guild.thread.send = AsyncMock(side_effect=discord.DiscordException("no"))

        async with _connected(monkeypatch) as chat:
            with pytest.raises(RemoteError, match="no"):
                await chat.ask(room="app", thread="heal · c0ffee00", text="x")

    # The daemon hands over the questions it already holds before the gateway
    # is entered.
    @staticmethod
    async def test_a_question_asked_before_the_remote_runs_waits_for_it(
        guild: _Guild, monkeypatch: pytest.MonkeyPatch
    ):
        guild.settled()
        monkeypatch.setattr(discord.Client, "start", _connected_for_good)
        chat = DiscordRemote(_SETUP)
        asking = asyncio.create_task(
            chat.ask(room="app", thread="heal · c0ffee00", text="push?")
        )
        await asyncio.sleep(0)
        waited = not asking.done()

        running = asyncio.create_task(chat.run(AsyncMock()))
        posted = await asking
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)

        assert waited
        assert posted == Posted(thread=str(_THREAD), message="1")


@pytest.mark.asyncio
class TestSay:
    @staticmethod
    async def test_it_is_sent_to_the_thread_over_as_many_messages_as_it_takes(
        monkeypatch: pytest.MonkeyPatch,
    ):
        thread = MagicMock(send=AsyncMock())
        got: list[int] = []
        monkeypatch.setattr(
            discord.Client,
            "get_partial_messageable",
            lambda _, thread_id: got.append(thread_id) or thread,
        )

        await DiscordRemote(_SETUP).say(
            thread="555", text="y" * 1000 + " " + "y" * 2000
        )

        assert got == [_THREAD]
        assert thread.send.await_args_list == [
            call("y" * 1000),
            call("y" * 1900),
            call("y" * 100),
        ]

    @staticmethod
    async def test_what_discord_refuses_is_a_remote_error(
        monkeypatch: pytest.MonkeyPatch,
    ):
        thread = MagicMock(send=AsyncMock(side_effect=discord.DiscordException("no")))
        monkeypatch.setattr(
            discord.Client, "get_partial_messageable", lambda _, __: thread
        )

        with pytest.raises(RemoteError, match="no"):
            await DiscordRemote(_SETUP).say(thread="555", text="→ push")


@pytest.mark.asyncio
class TestRun:
    @staticmethod
    async def test_a_message_in_a_thread_is_heard_and_the_word_back_is_replied(
        monkeypatch: pytest.MonkeyPatch,
    ):
        plain = _message()
        replying = _message(reference=MagicMock(message_id=42), content="2")
        tokens = _gateway(monkeypatch, plain, replying)
        hear = AsyncMock(side_effect=[None, "'2' is not one of a"])

        await DiscordRemote(_SETUP).run(hear)

        assert tokens == ["s3cret"]
        assert hear.await_args_list == [
            call(Heard(thread="555", reply_to=None, text="push")),
            call(Heard(thread="555", reply_to="42", text="2")),
        ]
        plain.reply.assert_not_awaited()
        replying.reply.assert_awaited_once_with("'2' is not one of a")

    @staticmethod
    async def test_a_bot_a_stranger_another_guild_a_dm_and_a_channel_are_not_heard(
        monkeypatch: pytest.MonkeyPatch,
    ):
        _gateway(
            monkeypatch,
            _message(author=MagicMock(bot=True, id=_OPERATOR)),
            _message(author=MagicMock(bot=False, id=_STRANGER)),
            _message(guild=MagicMock(id=404)),
            _message(guild=None),
            _message(channel=MagicMock(spec=discord.TextChannel, id=_THREAD)),
        )
        hear = AsyncMock()

        await DiscordRemote(_SETUP).run(hear)

        hear.assert_not_awaited()

    @staticmethod
    async def test_a_reaction_is_heard_as_its_emoji_and_the_word_back_is_sent(
        monkeypatch: pytest.MonkeyPatch,
    ):
        thread = _tapping(monkeypatch, _tap(), _tap(emoji="🎉", member=None))
        hear = AsyncMock(side_effect=[None, "🎉 is not one of 👍 ❌"])

        await DiscordRemote(_SETUP).run(hear)

        assert hear.await_args_list == [
            call(Tapped(thread="555", message="42", emoji="👍")),
            call(Tapped(thread="555", message="42", emoji="🎉")),
        ]
        thread.send.assert_awaited_once_with("🎉 is not one of 👍 ❌")

    @staticmethod
    async def test_a_reaction_of_a_bot_a_stranger_or_another_guild_is_not_heard(
        monkeypatch: pytest.MonkeyPatch,
    ):
        thread = _tapping(
            monkeypatch,
            _tap(member=MagicMock(bot=True)),
            _tap(user_id=_STRANGER),
            _tap(guild_id=404),
            _tap(guild_id=None),
        )
        hear = AsyncMock()

        await DiscordRemote(_SETUP).run(hear)

        hear.assert_not_awaited()
        thread.send.assert_not_awaited()

    @staticmethod
    async def test_a_token_discord_refuses_is_a_remote_error(
        monkeypatch: pytest.MonkeyPatch,
    ):
        monkeypatch.setattr(
            discord.Client,
            "start",
            AsyncMock(side_effect=discord.LoginFailure("Improper token")),
        )

        with pytest.raises(RemoteError, match="Improper token"):
            await DiscordRemote(_SETUP).run(AsyncMock())
