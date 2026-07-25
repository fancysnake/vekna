import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast, runtime_checkable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    TextBlock,
    query,
)
from pydantic import JsonValue

from vekna.lexicon import CodingCall, FocusReply, GateFn, register_focus

from ._pacts import ClaudeOptions

_DENY_MESSAGE = "denied by the vekna decide gate"


# The SDK's message dataclasses carry `Any`-typed fields, so naming those
# classes is itself an untyped expression. Match them structurally instead.
@runtime_checkable
class _AssistantLike(Protocol):
    @property
    def content(self) -> Sequence[object]: ...
    @property
    def model(self) -> str: ...


@runtime_checkable
class _ResultLike(Protocol):
    @property
    def num_turns(self) -> int: ...
    @property
    def session_id(self) -> str: ...
    @property
    def total_cost_usd(self) -> float | None: ...
    @property
    def result(self) -> str | None: ...


_PermissionResult = PermissionResultAllow | PermissionResultDeny
_CanUseTool = Callable[[str, dict[str, object], object], Awaitable[_PermissionResult]]


def _claude_options(focus_options: object | None) -> ClaudeOptions:
    if isinstance(focus_options, ClaudeOptions):
        return focus_options
    return ClaudeOptions()


def _permission_handler(gate: GateFn) -> _CanUseTool:
    async def can_use_tool(
        tool_name: str, input_data: dict[str, object], _context: object
    ) -> _PermissionResult:
        if await gate(tool_name):
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=_DENY_MESSAGE)

    return can_use_tool


def _agent_options(call: CodingCall, gate: GateFn | None) -> ClaudeAgentOptions:
    knobs = _claude_options(call.focus_options)
    if (permission_mode := knobs.permission_mode) is None:
        permission_mode = "default" if gate is not None else "bypassPermissions"
    output_format: dict[str, object] | None = None
    if call.output_schema is not None:
        output_format = {"type": "json_schema", "schema": call.output_schema}
    return ClaudeAgentOptions(
        model=call.model,
        system_prompt=call.system,
        cwd=call.cwd,
        permission_mode=permission_mode,
        can_use_tool=_permission_handler(gate) if gate is not None else None,
        allowed_tools=knobs.allowed_tools or [],
        max_turns=knobs.max_turns,
        effort=knobs.effort,
        output_format=output_format,
    )


def _structured(text: str, output_schema: object) -> JsonValue | None:
    if output_schema is None:
        return None
    try:
        return cast("JsonValue", json.loads(text))
    except ValueError:
        return None


class ClaudeCodingFocus:
    @staticmethod
    async def run(
        call: CodingCall, *, on_delta: Callable[[str], None], gate: GateFn | None
    ) -> FocusReply:
        options = _agent_options(call, gate)
        parts: list[str] = []
        telemetry: dict[str, JsonValue] = {}
        result_text: str | None = None
        async for message in query(prompt=call.prompt, options=options):
            if isinstance(message, _AssistantLike):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
                        on_delta(block.text)
            elif isinstance(message, _ResultLike):
                telemetry = {
                    "session_id": message.session_id,
                    "num_turns": message.num_turns,
                    "cost_usd": message.total_cost_usd,
                }
                result_text = message.result
        text = result_text if result_text is not None else "".join(parts)
        return FocusReply(
            text=text,
            structured=_structured(text, call.output_schema),
            telemetry=telemetry,
        )


def register() -> None:
    register_focus("coding", ClaudeCodingFocus())


register()
