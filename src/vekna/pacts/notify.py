from typing import Protocol

from pydantic import BaseModel

OK_RESPONSE = '{"status": "ok"}'
ERROR_RESPONSE_INVALID = '{"status": "error", "reason": "invalid request"}'


class NotifyRequest(BaseModel):
    pane_id: str


class NotifyClientMillProtocol(Protocol):
    async def notify(self, pane_id: str) -> None: ...
