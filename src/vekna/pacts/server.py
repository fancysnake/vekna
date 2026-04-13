from typing import Protocol


class ServerMillProtocol(Protocol):
    async def run(self) -> None: ...
