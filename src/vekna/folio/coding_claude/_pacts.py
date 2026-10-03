from typing import Literal, Self

from pydantic import BaseModel, model_validator

from vekna.lexicon import RitualError

PermissionMode = Literal[
    "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"
]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeOptionsError(RitualError):
    pass


class ClaudeOptions(BaseModel):
    permission_mode: PermissionMode | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] | None = None
    max_turns: int | None = None
    effort: EffortLevel | None = None

    # Opt-in and opt-out are two modes, not halves of one policy: beside each
    # other, which list an unlisted tool falls under is anyone's guess.
    # `ClaudeOptionsError` is not a `ValueError`, so pydantic lets it past.
    @model_validator(mode="after")
    def _one_tool_mode(self) -> Self:
        if self.allowed_tools is not None and self.disallowed_tools is not None:
            msg = "ClaudeOptions takes allowed_tools or disallowed_tools, not both"
            raise ClaudeOptionsError(msg)
        return self
