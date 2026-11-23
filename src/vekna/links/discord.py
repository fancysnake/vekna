import asyncio
import re

import discord
from typing_extensions import override

from vekna.pacts.remote import DiscordSetup, Hear, Heard, Posted, Remote, RemoteError

# Discord takes 2000 characters a message; the rest of a long text goes in the
# messages after it.
_MESSAGE = 1900
_NOT_A_CHANNEL_NAME = re.compile(r"[^a-z0-9_-]+")


class _Client(discord.Client):
    def __init__(self, *, guild: int, allow: frozenset[int]) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self._guild = guild
        self._allow = allow
        self.hear: Hear | None = None

    # discord.py finds this by its name.
    async def on_message(self, message: discord.Message) -> None:
        if (
            self.hear is None
            or message.author.bot
            or message.author.id not in self._allow
        ):
            return
        if (
            message.guild is None
            or message.guild.id != self._guild
            or not isinstance(message.channel, discord.Thread)
        ):
            return
        replied = message.reference.message_id if message.reference else None
        said = await self.hear(
            Heard(
                thread=str(message.channel.id),
                reply_to=None if replied is None else str(replied),
                text=message.content,
            )
        )
        if said is not None:
            await message.reply(said)


# One bot in one guild, dialling out over Discord's gateway. A room is a text
# channel under the configured category and a thread a public thread in it.
# Every question mentions the allowed users: a mention is what puts them in the
# thread and reaches their phone. Nobody else is heard.
class DiscordRemote(Remote):
    def __init__(self, setup: DiscordSetup) -> None:
        self._setup = setup
        self._client = _Client(guild=setup.guild, allow=setup.allow)
        self._mentions = " ".join(f"<@{user}>" for user in sorted(setup.allow))
        # The client refuses to be waited on before `run` has entered it, and a
        # question the daemon held from before it started is asked at once.
        self._entered = asyncio.Event()

    @override
    async def run(self, hear: Hear) -> None:
        self._client.hear = hear
        try:
            async with self._client:
                self._entered.set()
                await self._client.start(self._setup.token)
        except discord.DiscordException as error:
            raise RemoteError(str(error)) from error

    @override
    async def ask(self, *, room: str, thread: str, text: str) -> Posted:
        await self._entered.wait()
        await self._client.wait_until_ready()
        if (guild := self._client.get_guild(self._setup.guild)) is None:
            msg = f"the bot is not in the guild {self._setup.guild}"
            raise RemoteError(msg)
        worded = f"{self._mentions}\n{text}"
        try:
            found = await self._thread(await self._room(guild, room), thread)
            message = await _sent(found, worded)
        except discord.DiscordException as error:
            raise RemoteError(str(error)) from error
        return Posted(thread=str(found.id), message=str(message.id))

    @override
    async def say(self, *, thread: str, text: str) -> None:
        try:
            await _sent(self._client.get_partial_messageable(int(thread)), text)
        except discord.DiscordException as error:
            raise RemoteError(str(error)) from error

    async def _room(self, guild: discord.Guild, room: str) -> discord.TextChannel:
        category = discord.utils.get(guild.categories, name=self._setup.category)
        if category is None:
            category = await guild.create_category(self._setup.category)
        name = channel_name(room)
        if (found := discord.utils.get(category.text_channels, name=name)) is None:
            return await guild.create_text_channel(name, category=category)
        return found

    # shortcut: an archived thread is not among `threads`, so a cast that asks
    # again after Discord archived its thread gets a second one of the same
    # name; fetching the archived threads is the upgrade.
    @staticmethod
    async def _thread(channel: discord.TextChannel, name: str) -> discord.Thread:
        if (found := discord.utils.get(channel.threads, name=name)) is None:
            return await channel.create_thread(
                name=name, type=discord.ChannelType.public_thread
            )
        return found


# The message a reply to the text is aimed at: the last of the messages the
# text is split over.
async def _sent(target: discord.abc.Messageable, text: str) -> discord.Message:
    return [
        await target.send(text[at : at + _MESSAGE])
        for at in range(0, len(text), _MESSAGE)
    ][-1]


# Discord rewrites a channel's name on its side. Written its way here, so the
# channel made for a project is the one found for it the next time.
def channel_name(room: str) -> str:
    return _NOT_A_CHANNEL_NAME.sub("-", room.lower()).strip("-") or "project"
