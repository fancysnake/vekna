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
# and which key to file the reply under. A key is the thread's identity and
# outlives the call; `resume` is what this one call carries in.
@dataclass(frozen=True)
class _Thread:
    declared: Session
    resume: str | None
    key: str | None


# Both checks take `object` rather than the parameter's own type, and that is
# what lets them exist: whether an author's `rituals.py` is type-checked is up
# to them, so the runtime is the only place `session=None` or `key=3` is caught
# in general — and mypy, reading the annotation, would call a guard against an
# already-narrowed type unreachable.
def _declared(session: Session) -> Session:
    # Compared rather than looked up with `Session(...)`, which takes a `str`
    # and so would not see the arguments this check is here for.
    for word in Session:
        if session == word:
            return word
    wanted = f"{Session.NEW.value!r} or {Session.CONTINUE.value!r}"
    msg = f"session takes {wanted} — not {session!r}"
    raise CodingSessionError(msg)


def _keyed(key: str | None) -> str | None:
    if key is None:
        return None
    # Stripping once, here, is what makes it one classification: an unnamed
    # thread is a typo that would otherwise work — `key=""` opens a thread
    # under the empty string and reads as a fresh session forever — and
    # `" repair"` is the same typo wearing the name of a real thread it would
    # never join.
    if isinstance(key, str) and (stripped := key.strip()):
        return stripped
    msg = f"key names the thread this call is on — not {key!r}"
    raise CodingSessionError(msg)


# `new` starts fresh whether or not the call is keyed: a key says which thread
# the reply is filed under, and `new` deliberately restarts that thread.
# Unkeyed `continue` is the last session *any* coding rite produced, not the
# last `continue` call: a retry that wants the agent to remember what it already
# tried follows a first attempt written as a plain `coding(...)`, which under
# the default records no key of its own. Reading only its own kind would start
# that retry fresh while looking like it resumed — the failure the declaration
# exists to make visible.
def _thread(*, context: RiteContext, session: Session, key: str | None) -> _Thread:
    declared = _declared(session)
    keyed = _keyed(key)
    if declared == Session.NEW:
        return _Thread(declared=declared, resume=None, key=keyed)
    book = context.sessions
    resume = book.named(keyed) if keyed is not None else book.latest
    return _Thread(declared=declared, resume=resume, key=keyed)


# A reply with no id cannot be filed, and a call that declared a thread has to
# hear about it: the next call on that thread would otherwise resume whatever
# ran before this one while the ritual reads as threaded. Said out loud rather
# than raised — the agent's work is done and valid, and a Focus that reports no
# ids would otherwise be unusable with threads at all. A call that declared
# nothing stays quiet, having claimed nothing to lose.
def _record(*, context: RiteContext, thread: _Thread, session_id: str | None) -> None:
    if session_id is not None:
        context.sessions.record(session_id, name=thread.key)
        return
    if thread.declared == Session.NEW and thread.key is None:
        return
    label = f"key {thread.key!r}" if thread.key is not None else "the running session"
    emit_delta(f"the focus reported no session id: nothing recorded for {label}")


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
    session: Session = Session.NEW,
    key: str | None = None,
) -> CodingResult: ...


@overload
async def coding(
    prompt: str,
    *,
    output: type[_OutputT],
    opts: CodingOpts | None = None,
    session: Session = Session.NEW,
    key: str | None = None,
) -> _OutputT: ...


@medium
async def coding(
    prompt: str,
    *,
    output: type[_OutputT] | None = None,
    opts: CodingOpts | None = None,
    session: Session = Session.NEW,
    key: str | None = None,
) -> CodingResult | _OutputT:
    focus = cast("CodingFocusProtocol", resolve_focus(MEDIUM))
    context = current_rite()
    resolved = opts if opts is not None else CodingOpts()
    thread = _thread(context=context, session=session, key=key)
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
    _record(context=context, thread=thread, session_id=reply.session_id)
    # The declaration, not just the id: whether the author meant this rite to
    # carry context is the thing the journal cannot read off `session_id`.
    telemetry: dict[str, JsonValue] = {
        "session": thread.declared.value,
        "key": thread.key,
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
