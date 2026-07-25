import asyncio
from collections.abc import AsyncIterator

from ._pacts import WireMessage, decode_frame


async def read_frames(reader: asyncio.StreamReader) -> AsyncIterator[WireMessage]:
    async for raw in reader:
        if stripped := raw.strip():
            yield decode_frame(stripped)
