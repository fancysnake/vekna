import asyncio
import logging
import re
from collections.abc import Sequence

import discord
from typing_extensions import override

from vekna.pacts.remote import DiscordSetup, Hear, Heard, Posted, Remote, RemoteError

# Discord takes 2000 characters a message.
_MESSAGE = 1900
# How far back in a thread a question still waiting is looked for.
_LOOK_BACK = 50
_NOT_A_CHANNEL_NAME = re.compile(r"[^a-z0-9_-]+")

_log = logging.getLogger(__name__)


class _Client(discord.Client):
    def __init__(self, *, guild: int, allow: frozenset[int]) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.guild_reactions = True
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

    # discord.py finds this by its name. The raw event, because a question
    # posted before the daemon restarted is not in the client's cache. Which
    # thread and which message it is on is for `hear` to judge.
    async def on_raw_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        if (
            self.hear is None
            or payload.guild_id != self._guild
            or payload.user_id not in self._allow
            or (payload.member is not None and payload.member.bot)
        ):
            return
        said = await self.hear(
            Heard(
                thread=str(payload.channel_id),
                reply_to=str(payload.message_id),
                text=str(payload.emoji),
                reaction=True,
            )
        )
        if said is not None:
            await self.get_partial_messageable(payload.channel_id).send(said)


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
    async def ask(
        self, *, room: str, thread: str, text: str, reactions: Sequence[str] = ()
    ) -> Posted:
        await self._entered.wait()
        await self._client.wait_until_ready()
        if (guild := self._client.get_guild(self._setup.guild)) is None:
            msg = f"the bot is not in the guild {self._setup.guild}"
            raise RemoteError(msg)
        pieces = _pieces(f"{self._mentions}\n{text}".strip())
        try:
            found = await self._thread(await self._room(guild, room), thread)
            if (waiting := await self._waiting(found, pieces[-1])) is not None:
                return waiting
            message = await _sent(found, pieces)
        except discord.DiscordException as error:
            raise RemoteError(str(error)) from error
        await _offered(message, reactions)
        return Posted(thread=str(found.id), message=str(message.id))

    @override
    async def say(self, *, thread: str, text: str) -> None:
        try:
            target = self._client.get_partial_messageable(int(thread))
            await _sent(target, _pieces(text.strip()))
        except discord.DiscordException as error:
            raise RemoteError(str(error)) from error

    # The question as the last thing the bot said in the thread, with what the
    # allowed users wrote under it: a daemon that restarted finds the question
    # it posted before, and the answers written while it was away.
    # shortcut: a reaction put on the question while the daemon was away is
    # not read, so that question waits for a second tap or a written reply;
    # reading the found message's reactions is the upgrade.
    async def _waiting(self, thread: discord.Thread, ending: str) -> Posted | None:
        unheard: list[str] = []
        async for message in thread.history(limit=_LOOK_BACK):
            if message.author.bot:
                if message.content != ending:
                    return None
                return Posted(
                    thread=str(thread.id),
                    message=str(message.id),
                    unheard=tuple(reversed(unheard)),
                )
            if message.author.id in self._setup.allow:
                unheard.append(message.content)
        return None

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
async def _sent(target: discord.abc.Messageable, pieces: list[str]) -> discord.Message:
    return [await target.send(piece) for piece in pieces][-1]


# The question stands once it is posted: a reaction Discord refuses costs the
# tap, and a written reply still answers.
async def _offered(message: discord.Message, reactions: Sequence[str]) -> None:
    try:
        for emoji in reactions:
            await message.add_reaction(emoji)
    except discord.DiscordException as error:
        _log.warning("could not put reactions under a question: %s", error)


# A long text over several messages, cut at the last line break that fits,
# else at the last space, else inside a word.
# shortcut: a cut inside a code span leaves it open in one message and
# unopened in the next; closing and reopening the span is the upgrade.
def _pieces(text: str) -> list[str]:
    if len(text) <= _MESSAGE:
        return [text]
    fits = _MESSAGE + 1
    cut = (
        max(text.rfind("\n", 0, fits), 0)
        or max(text.rfind(" ", 0, fits), 0)
        or _MESSAGE
    )
    return [text[:cut], *_pieces(text[cut:].strip())]


# Discord rewrites a channel's name on its side. Written its way here, so the
# channel made for a project is the one found for it the next time.
def channel_name(room: str) -> str:
    return _NOT_A_CHANNEL_NAME.sub("-", room.lower()).strip("-") or "project"
