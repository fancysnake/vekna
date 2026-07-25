import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast, runtime_checkable

from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    TextBlock,
    create_sdk_mcp_server,
    query,
    tool,
)
from pydantic import JsonValue

from vekna.lexicon import AskFn, CodingCall, FocusReply, GateFn, register_focus

from ._pacts import ClaudeOptions

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
_ToolHandler = Callable[[dict[str, object]], Awaitable[dict[str, object]]]
_ToolFactory = Callable[[_ToolHandler], object]


# The SDK's server and option types are `Any`-tainted, so both constructors are
# reached through signatures of our own rather than naming them.
class _ServerFactory(Protocol):
    def __call__(self, name: str, *, tools: list[object]) -> object: ...


class _OptionsFactory(Protocol):
    def __call__(self, **knobs: object) -> ClaudeAgentOptions: ...


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


# The tool runs in *this* process — the CLI subprocess calls back over the
# SDK's control protocol and the agent blocks until the operator answers.
def _ask_server(ask: AskFn) -> object:
    async def answer(args: dict[str, object]) -> dict[str, object]:
        raw = args.get("options")
        offered = [str(item) for item in raw] if isinstance(raw, list) and raw else None
        reply = await ask(str(args.get("question", "")), offered)
        return {"content": [{"type": "text", "text": reply}]}

    build = cast("_ToolFactory", tool(_ASK, _ASK_DESCRIPTION, _ASK_SCHEMA))
    serve = cast("_ServerFactory", create_sdk_mcp_server)
    tools: list[object] = [build(answer)]
    return serve(_SERVER, tools=tools)


def _system_prompt(system: str | None) -> str | dict[str, str]:
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
    output_format: dict[str, object] | None = None
    if call.output_schema is not None:
        output_format = {"type": "json_schema", "schema": call.output_schema}
    allowed: list[str] = [*(knobs.allowed_tools or []), _ASK_TOOL]
    servers: dict[str, object] = {_SERVER: _ask_server(ask)}
    build = cast("_OptionsFactory", ClaudeAgentOptions)
    return build(
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
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        options = _agent_options(call=call, gate=gate, ask=ask)
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
