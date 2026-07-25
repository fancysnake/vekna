from typing import Literal

from pydantic import BaseModel

PermissionMode = Literal[
    "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"
]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeOptions(BaseModel):
    permission_mode: PermissionMode | None = None
    allowed_tools: list[str] | None = None
    max_turns: int | None = None
    effort: EffortLevel | None = None
