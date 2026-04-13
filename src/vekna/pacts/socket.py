from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class SocketServerLinkProtocol(Protocol):
    async def start(self, handler: Callable[[str], Awaitable[str]]) -> None: ...

    async def stop(self) -> None: ...


class SocketClientLinkProtocol(Protocol):
    async def send(self, message: str) -> str: ...
