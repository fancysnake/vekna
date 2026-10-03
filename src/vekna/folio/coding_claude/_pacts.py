from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    ValidationError,
    model_validator,
)

from vekna.lexicon import RitualError

PermissionMode = Literal[
    "default", "acceptEdits", "plan", "dontAsk", "bypassPermissions", "auto"
]
EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class ClaudeOptionsError(RitualError):
    pass


# `forbid` because a misspelled `disallowed_tools` dropped in silence leaves the
# agent every tool the field was there to take away. Wrapped for the same reason
# `CodingOpts` is: `ClaudeOptionsError` is not a `ValueError`, so pydantic lets
# it past, and the cast reports an author's mistake rather than a traceback.
class ClaudeOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_mode: PermissionMode | None = None
    allowed_tools: list[str] | None = None
    disallowed_tools: list[str] = []
    max_turns: int | None = None
    effort: EffortLevel | None = None

    @model_validator(mode="wrap")
    @classmethod
    def _refuse_invalid(
        cls, values: object, handler: ModelWrapValidatorHandler[Self]
    ) -> Self:
        try:
            return handler(values)
        except ValidationError as error:
            said = "; ".join(
                f"{'.'.join(str(part) for part in detail['loc'])}: {detail['msg']}"
                for detail in error.errors()
            )
            msg = f"{cls.__name__} refused what it was given — {said}"
            raise ClaudeOptionsError(msg) from error
