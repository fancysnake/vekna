from typing import Protocol

from pydantic import BaseModel

from vekna.pacts.socket import Response

OK_RESPONSE = Response(status="ok")
ERROR_RESPONSE_INVALID = Response(status="error", reason="invalid request")
ERROR_PAYLOAD_INVALID_NOTIFICATION = "invalid claude notification payload"


class Event(BaseModel):
    app: str
    hook: str
    payload: str
    meta: dict[str, str]


class NotifyClientMillProtocol(Protocol):
    async def notify(
        self, app: str, hook: str, payload: str, meta: dict[str, str]
    ) -> None: ...

    async def request(self, event: Event) -> Response: ...
