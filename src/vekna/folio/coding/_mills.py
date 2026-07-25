from collections.abc import Sequence
from typing import TYPE_CHECKING, TypeVar, cast, overload

from pydantic import JsonValue, TypeAdapter, ValidationError

from vekna.lexicon import (
    Channel,
    CodingCall,
    GateFn,
    current_rite,
    medium,
    record_result,
    resolve_focus,
)

from ._pacts import CodingOpts, CodingOutputError, CodingResult

if TYPE_CHECKING:
    from vekna.lexicon import CodingFocusProtocol

_OutputT = TypeVar("_OutputT")

_INSTALL_HINT = "the Claude Focus needs claude-agent-sdk: pip install claude-agent-sdk"


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


def _validate_output(output: type[_OutputT], text: str, structured: object) -> _OutputT:
    adapter: TypeAdapter[_OutputT] = TypeAdapter(output)
    try:
        if structured is not None:
            return adapter.validate_python(structured)
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
    focus_options: object | None = None,
) -> CodingResult: ...


@overload
async def coding(
    prompt: str,
    *,
    output: type[_OutputT],
    opts: CodingOpts | None = None,
    gate_tools: Sequence[str] | None = None,
    focus_options: object | None = None,
) -> _OutputT: ...


@medium
async def coding(
    prompt: str,
    *,
    output: type[_OutputT] | None = None,
    opts: CodingOpts | None = None,
    gate_tools: Sequence[str] | None = None,
    focus_options: object | None = None,
) -> CodingResult | _OutputT:
    focus = cast("CodingFocusProtocol", resolve_focus("coding", hint=_INSTALL_HINT))
    context = current_rite()
    rite_id = context.parent_id

    def on_delta(text: str) -> None:
        if rite_id is not None:
            context.grimoire.rite_delta(rite_id, text)

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
        call, on_delta=on_delta, gate=_make_gate(context.channel, gate_tools)
    )
    record_result(dict(reply.telemetry))
    if output is None:
        payload: dict[str, JsonValue] = {**reply.telemetry, "text": reply.text}
        return CodingResult.model_validate(payload)
    return _validate_output(output, reply.text, reply.structured)
