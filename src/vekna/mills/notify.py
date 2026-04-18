from vekna.pacts.notify import Event
from vekna.pacts.socket import SocketClientLinkProtocol


class NotifyClientMill:
    def __init__(self, socket_client: SocketClientLinkProtocol) -> None:
        self._socket_client = socket_client

    async def notify(
        self, app: str, hook: str, payload: str, meta: dict[str, str]
    ) -> None:
        event = Event(app=app, hook=hook, payload=payload, meta=meta)
        await self._socket_client.send(event.model_dump_json())
