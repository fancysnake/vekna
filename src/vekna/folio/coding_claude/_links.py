from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from claude_agent_sdk.types import (
    ContentBlock,
    McpHttpServerConfig,
    McpSdkServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
    PermissionResultAllow,
    PermissionResultDeny,
    SystemPromptFile,
    SystemPromptPreset,
    ToolPermissionContext,
)
from pydantic import BaseModel, JsonValue

from vekna.lexicon import AskFn, CodingCall, CodingFocusProtocol, FocusReply, GateFn

from ._pacts import ClaudeOptions

if TYPE_CHECKING:
    from pathlib import Path

    from claude_agent_sdk import SdkMcpTool

_DENY_MESSAGE = "denied by the vekna decide gate"

_SERVER = "vekna"
_ASK = "ask_human"
_ASK_TOOL = f"mcp__{_SERVER}__{_ASK}"
_ASK_DESCRIPTION = (
    "Ask the operator a question and wait for their answer. Use this whenever "
    "a decision is theirs to make — where a test belongs, which of several "
    "valid approaches to take, anything you would otherwise have to guess at."
)
_ASK_SCHEMA: dict[str, JsonValue] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "The question to ask."},
        "options": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Answers to choose between; omit for a free-form answer.",
        },
    },
    "required": ["question"],
}
_ASK_INSTRUCTION = (
    f"When a choice is the operator's to make, call the {_ASK_TOOL} tool and "
    "wait for the answer rather than guessing. Pass `options` when the answer "
    "is one of a known set."
)


# The SDK's message dataclasses carry `Any`-typed fields, so naming those
# classes is itself an untyped expression. Match them structurally instead.
@runtime_checkable
class _AssistantLike(Protocol):
    @property
    def content(self) -> str | list[ContentBlock]: ...
    @property
    def model(self) -> str: ...


# `content` is a union, and a `str` is iterable — so looping it directly walks
# the message one character at a time and matches `TextBlock` on none of them,
# silently dropping the whole reply from the stream.
def _texts(content: str | list[ContentBlock]) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [block.text for block in content if isinstance(block, TextBlock)]


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


def _claude_options(focus_options: BaseModel | None) -> ClaudeOptions:
    if isinstance(focus_options, ClaudeOptions):
        return focus_options
    return ClaudeOptions()


def _permission_handler(
    gate: GateFn,
) -> Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResultAllow | PermissionResultDeny],
]:
    async def can_use_tool(
        tool_name: str, input_data: dict[str, Any], _context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        if await gate(tool_name):
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message=_DENY_MESSAGE)

    return can_use_tool


# The tool runs in *this* process — the CLI subprocess calls back over the
# SDK's control protocol and the agent blocks until the operator answers.
def _ask_server(
    ask: AskFn,
) -> (
    McpStdioServerConfig | McpSSEServerConfig | McpHttpServerConfig | McpSdkServerConfig
):
    async def answer(args: Any) -> dict[str, Any]:  # ruff: ignore [any-type]
        raw = args.get("options")
        offered = [str(item) for item in raw] if isinstance(raw, list) and raw else None
        reply = await ask(str(args.get("question", "")), offered)
        return {"content": [{"type": "text", "text": reply}]}

    build = tool(_ASK, _ASK_DESCRIPTION, _ASK_SCHEMA)
    serve = create_sdk_mcp_server
    tools: list[SdkMcpTool[Any]] | None = [build(answer)]
    return serve(_SERVER, tools=tools)


def _system_prompt(
    system: str | None,
) -> str | SystemPromptPreset | SystemPromptFile | None:
    # Appending to the preset keeps Claude Code's own system prompt; a plain
    # string would replace it.
    if system is None:
        return {"type": "preset", "preset": "claude_code", "append": _ASK_INSTRUCTION}
    return f"{system}\n\n{_ASK_INSTRUCTION}"


def _agent_options(
    *, call: CodingCall, gate: GateFn | None, ask: AskFn
) -> ClaudeAgentOptions:
    knobs = _claude_options(call.focus_options)
    if (permission_mode := knobs.permission_mode) is None:
        permission_mode = "default" if gate is not None else "bypassPermissions"
    output_format: dict[str, str | dict[str, JsonValue]] | None = None
    if call.output_schema is not None:
        output_format = {"type": "json_schema", "schema": call.output_schema}
    allowed: list[str] = [*(knobs.allowed_tools or []), _ASK_TOOL]
    servers: (
        dict[
            str,
            McpStdioServerConfig
            | McpSSEServerConfig
            | McpHttpServerConfig
            | McpSdkServerConfig,
        ]
        | str
        | Path
    ) = {_SERVER: _ask_server(ask)}
    return ClaudeAgentOptions(
        model=call.model,
        system_prompt=_system_prompt(call.system),
        cwd=call.cwd,
        permission_mode=permission_mode,
        can_use_tool=_permission_handler(gate) if gate is not None else None,
        allowed_tools=allowed,
        mcp_servers=servers,
        max_turns=knobs.max_turns,
        effort=knobs.effort,
        output_format=output_format,
    )


class ClaudeCodingFocus(CodingFocusProtocol):
    @staticmethod
    async def run(
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        options = _agent_options(call=call, gate=gate, ask=ask)
        parts: list[str] = []
        session_id: str | None = None
        num_turns: int | None = None
        cost_usd: float | None = None
        result_text: str | None = None
        async for message in query(prompt=call.prompt, options=options):
            if isinstance(message, _AssistantLike):
                for text in _texts(message.content):
                    parts.append(text)
                    on_delta(text)
            elif isinstance(message, _ResultLike):
                session_id = message.session_id
                num_turns = message.num_turns
                cost_usd = message.total_cost_usd
                result_text = message.result
        return FocusReply(
            text=result_text if result_text is not None else "".join(parts),
            session_id=session_id,
            num_turns=num_turns,
            cost_usd=cost_usd,
        )
