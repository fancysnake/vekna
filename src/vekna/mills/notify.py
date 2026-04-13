from typing import TYPE_CHECKING

from vekna.pacts.notify import NotifyRequest

if TYPE_CHECKING:
    from vekna.pacts.socket import SocketClientLinkProtocol


class NotifyClientMill:
    def __init__(self, socket_client: SocketClientLinkProtocol) -> None:
        self._socket_client = socket_client

    async def notify(self, pane_id: str) -> None:
        request = NotifyRequest(pane_id=pane_id)
        await self._socket_client.send(request.model_dump_json())
