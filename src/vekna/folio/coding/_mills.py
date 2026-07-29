from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, cast, overload

from pydantic import JsonValue, TypeAdapter, ValidationError

from vekna.lexicon import (
    AskFn,
    Channel,
    CodingCall,
    GateFn,
    RiteContext,
    StringOutput,
    current_rite,
    emit_delta,
    medium,
    record_result,
    resolve_focus,
)

from ._pacts import (
    CodingOpts,
    CodingOutputError,
    CodingResult,
    CodingSessionError,
    Session,
)

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


# What the rest of the call needs off a declaration: which session to resume,
# and which name to file the reply under. `name` is None for both reserved
# words, because neither of them names anything.
@dataclass(frozen=True)
class _Thread:
    declared: str
    resume: str | None
    name: str | None


# `new` is the absence of a thread, so it resolves to nothing and starts fresh.
# `continue` is the last session *any* coding rite produced, not the last
# `continue` call: a retry that wants the agent to remember what it already tried
# follows a first attempt written as a plain `coding(...)`, which under the
# default records no thread of its own. Reading only its own kind would start
# that retry fresh while looking like it resumed — the failure the declaration
# exists to make visible.
def _thread(*, context: RiteContext, session: Session | str) -> _Thread:
    # Stripping once, here, is what makes it one classification: an unnamed
    # thread is a typo that would otherwise work — `session=""` resolves to
    # nothing, records under the empty string, and reads as a fresh session
    # forever — and `" repair"` is the same typo wearing the name of a real
    # thread it would never join.
    if not (declared := str(session).strip()):
        msg = "session takes 'new', 'continue', or a thread name — not a blank one"
        raise CodingSessionError(msg)
    book = context.sessions
    if declared == Session.NEW:
        return _Thread(declared=declared, resume=None, name=None)
    if declared == Session.CONTINUE:
        return _Thread(declared=declared, resume=book.latest, name=None)
    return _Thread(declared=declared, resume=book.named(declared), name=declared)


def _validate_output(*, output: type[_OutputT], text: str) -> _OutputT:
    adapter: TypeAdapter[_OutputT] = TypeAdapter(output)
    try:
        return adapter.validate_json(text)
    except (ValidationError, ValueError) as error:
        msg = f"agent output does not validate as {output!r}: {error}"
        raise CodingOutputError(msg) from error


@overload
async def coding(
    prompt: str, *, opts: CodingOpts | None = None, session: Session | str = Session.NEW
) -> CodingResult: ...


@overload
async def coding(
    prompt: str,
    *,
    output: type[_OutputT],
    opts: CodingOpts | None = None,
    session: Session | str = Session.NEW,
) -> _OutputT: ...


@medium
async def coding(
    prompt: str,
    *,
    output: type[_OutputT] | None = None,
    opts: CodingOpts | None = None,
    session: Session | str = Session.NEW,
) -> CodingResult | _OutputT:
    focus = cast("CodingFocusProtocol", resolve_focus(MEDIUM))
    context = current_rite()
    resolved = opts if opts is not None else CodingOpts()
    thread = _thread(context=context, session=session)
    schema: dict[str, JsonValue] | None = None
    if output is not None:
        schema = TypeAdapter(output).json_schema()
    call = CodingCall(
        prompt=prompt,
        model=resolved.model,
        system=resolved.system,
        cwd=resolved.cwd,
        output_schema=schema,
        focus_options=resolved.focus_options,
        resume=thread.resume,
    )
    reply = await focus.run(
        call,
        on_delta=emit_delta,
        gate=_make_gate(context.channel, resolved.gate_tools),
        ask=_make_ask(context.channel),
    )
    if reply.session_id is not None:
        context.sessions.record(reply.session_id, name=thread.name)
    # The declaration, not just the id: whether the author meant this rite to
    # carry context is the thing the journal cannot read off `session_id`.
    telemetry: dict[str, JsonValue] = {
        "session": thread.declared,
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
async def one_shot(prompt: str) -> StringOutput:
    return StringOutput(output=(await coding(prompt)).text)
