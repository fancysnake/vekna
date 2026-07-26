from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar, cast, overload

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError

from vekna.lexicon import (
    AskFn,
    Channel,
    CodingCall,
    GateFn,
    current_rite,
    emit_delta,
    medium,
    record_result,
    resolve_focus,
)

from ._pacts import CodingOpts, CodingOutputError, CodingResult

if TYPE_CHECKING:
    from vekna.lexicon import CodingFocusProtocol

_OutputT = TypeVar("_OutputT")

MEDIUM = "coding"
INSTALL_HINT = "the Claude Focus needs claude-agent-sdk: pip install claude-agent-sdk"


def _make_gate(channel: Channel, gate_tools: Sequence[str] | None) -> GateFn | None:
    if gate_tools is None:
        return None
    watched = frozenset(gate_tools)

    async def gate(tool: str) -> bool:
        if tool not in watched:
            return True
        answer = await channel.decide(prompt=f"allow tool {tool!r}?")
        return answer == "yes"

    return gate


def _make_ask(channel: Channel) -> AskFn:
    # The agent asks; the human answers on whichever surface is attached.
    async def ask(question: str, options: Sequence[str] | None) -> str:
        if options:
            return await channel.decide(prompt=question, options=options)
        return await channel.decide(prompt=question, free=True)

    return ask


def _validate_output(*, output: type[_OutputT], text: str) -> _OutputT:
    adapter: TypeAdapter[_OutputT] = TypeAdapter(output)
    try:
        return adapter.validate_json(text)
    except (ValidationError, ValueError) as error:
        msg = f"agent output does not validate as {output!r}: {error}"
        raise CodingOutputError(msg) from error


@overload
async def coding(
    prompt: str,
    *,
    opts: CodingOpts | None = None,
    gate_tools: Sequence[str] | None = None,
    focus_options: BaseModel | None = None,
) -> CodingResult: ...


@overload
async def coding(
    prompt: str,
    *,
    output: type[_OutputT],
    opts: CodingOpts | None = None,
    gate_tools: Sequence[str] | None = None,
    focus_options: BaseModel | None = None,
) -> _OutputT: ...


@medium
async def coding(
    prompt: str,
    *,
    output: type[_OutputT] | None = None,
    opts: CodingOpts | None = None,
    gate_tools: Sequence[str] | None = None,
    focus_options: BaseModel | None = None,
) -> CodingResult | _OutputT:
    focus = cast("CodingFocusProtocol", resolve_focus(MEDIUM))
    context = current_rite()
    schema: dict[str, JsonValue] | None = None
    if output is not None:
        schema = cast("dict[str, JsonValue]", TypeAdapter(output).json_schema())
    resolved = opts if opts is not None else CodingOpts()
    call = CodingCall(
        prompt=prompt,
        model=resolved.model,
        system=resolved.system,
        cwd=resolved.cwd,
        output_schema=schema,
        focus_options=focus_options,
    )
    reply = await focus.run(
        call,
        on_delta=emit_delta,
        gate=_make_gate(context.channel, gate_tools),
        ask=_make_ask(context.channel),
    )
    telemetry: dict[str, JsonValue] = {
        "session_id": reply.session_id,
        "num_turns": reply.num_turns,
        "cost_usd": reply.cost_usd,
    }
    record_result(telemetry)
    if output is None:
        return CodingResult(
            text=reply.text,
            session_id=reply.session_id,
            num_turns=reply.num_turns,
            cost_usd=reply.cost_usd,
        )
    return _validate_output(output=output, text=reply.text)


# `vekna cast --prompt` reaches the medium through this, so the lexicon needs
# no import of its own — and no structural type for the result.
async def one_shot(prompt: str) -> str:
    return (await coding(prompt)).text
