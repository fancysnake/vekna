from typing import Protocol

from pydantic import BaseModel

OK_RESPONSE = '{"status": "ok"}'
ERROR_RESPONSE_INVALID = '{"status": "error", "reason": "invalid request"}'
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
