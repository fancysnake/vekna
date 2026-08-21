import contextlib
from collections.abc import Callable, Iterator, Sequence
from contextvars import ContextVar
from typing import TypeVar

from pydantic import BaseModel

from vekna.lexicon._pacts import (
    AskFn,
    Channel,
    CodingCall,
    CodingFocusProtocol,
    FocusReply,
    GateFn,
    ShellCall,
    ShellFocusProtocol,
    ShellReply,
)

from ._pacts import Answer, Asked, CodingAnswer, ScriptProtocol, TrialScriptError

_YES = "yes"
_NO = "no"

_DoubleT = TypeVar("_DoubleT")


class CodingDouble:
    def __init__(self, script: ScriptProtocol[CodingAnswer]) -> None:
        self._script = script
        self.calls: list[CodingCall] = []
        self.gated: list[tuple[str, bool]] = []
        self.answered: list[str] = []

    # A model rather than text, because `coding(..., output=Judgement)` answers
    # through the medium's own validation: serialising here is what lets a test
    # say what it means and still run that validation on the way back.
    # `uses` and `asks` are copied rather than held: a caller's list stays the
    # caller's to mutate, and a script that changed under one would be answering
    # a different call than the one the test wrote.
    def replies(
        self,
        reply: str | BaseModel = "",
        *,
        when: str | None = None,
        always: bool = False,
        uses: Sequence[str] = (),
        asks: Sequence[str] = (),
    ) -> None:
        # Narrowed against `str`, not against `BaseModel`: pydantic's class
        # object is Any-typed, and this module is not one of the ones exempt
        # from saying so.
        text = reply if isinstance(reply, str) else reply.model_dump_json()
        answer = CodingAnswer(text=text, uses=tuple(uses), asks=tuple(asks))
        self._script.add(Answer(value=answer, when=when, always=always))

    @property
    def prompts(self) -> list[str]:
        return [call.prompt for call in self.calls]

    # What a real focus does with a thread: a call that resumes stays on its
    # session, and one that does not is handed a new id. `s1`, `s2` by arrival —
    # which is what makes `calls[1].resume == "s1"` an assertion worth writing.
    async def answer(
        self,
        *,
        call: CodingCall,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        self.calls.append(call)
        scripted = self._script.take(call.prompt)
        # No gate means the call declared no `gate_tools`, which is the medium
        # saying every tool is allowed — not that the tool went unused.
        for tool in scripted.uses:
            self.gated.append((tool, True if gate is None else await gate(tool)))
        for question in scripted.asks:
            self.answered.append(await ask(question, None))
        if scripted.text:
            on_delta(scripted.text)
        session_id = call.resume if call.resume is not None else f"s{len(self.calls)}"
        return FocusReply(text=scripted.text, session_id=session_id)


class ShellDouble:
    def __init__(self, script: ScriptProtocol[ShellReply]) -> None:
        self._script = script
        self.calls: list[ShellCall] = []

    def replies(
        self,
        *,
        when: str | None = None,
        always: bool = False,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
    ) -> None:
        reply = ShellReply(stdout=stdout, stderr=stderr, exit_code=exit_code)
        self._script.add(Answer(value=reply, when=when, always=always))

    @property
    def commands(self) -> list[str]:
        return [call.command for call in self.calls]

    # The lines go out the way bash's do, so a ritual that streams and a
    # renderer that reads deltas both behave as they will in a real cast.
    def answer(
        self, call: ShellCall, *, on_line: Callable[[str], None] | None
    ) -> ShellReply:
        self.calls.append(call)
        reply = self._script.take(call.command)
        if on_line is not None:
            for line in (reply.stdout + reply.stderr).splitlines():
                on_line(line)
        return reply


# A Channel, not a Focus: `decide` reads the channel off the running rite, so
# there is no registry entry to stand in. Coding's `gate_tools` prompts and the
# agent's own questions are built out of the same channel, so they arrive here
# too — and are scripted the same way.
class DecideDouble(Channel):
    def __init__(self, script: ScriptProtocol[str]) -> None:
        self._script = script
        self.asked: list[Asked] = []

    # Keyword-only, and `True` rather than `"yes"` because that is what the
    # medium hands the ritual back. A bare `answers(True)` would be a boolean
    # positional, which reads as nothing at the call site.
    def answers(
        self, *, answer: bool | str, when: str | None = None, always: bool = False
    ) -> None:
        value = (_YES if answer else _NO) if isinstance(answer, bool) else answer
        self._script.add(Answer(value=value, when=when, always=always))

    @property
    def prompts(self) -> list[str]:
        return [asked.prompt for asked in self.asked]

    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        offered = None if options is None else tuple(options)
        self.asked.append(Asked(prompt=prompt, options=offered, free=free))
        answer = self._script.take(prompt)
        return self._offered(answer=answer, options=offered, free=free)

    # The real channel returns a member of what it offered or raises. A test
    # scripting "repair" for a step offering ["fix", "stop"] is testing a ritual
    # that does not exist, so it is refused here rather than three steps later.
    # Under `free` the options are suggestions — an agent's `ask_human` always
    # arrives that way — and answering past them is the point, so nothing to
    # check.
    @staticmethod
    def _offered(*, answer: str, options: Sequence[str] | None, free: bool) -> str:
        if free:
            return answer
        allowed = (_YES, _NO) if options is None else tuple(options)
        if answer in allowed:
            return answer
        msg = f"{answer!r} is not one of the offered answers: {list(allowed)}"
        raise TrialScriptError(msg)


# A Focus is static — the protocol says so, and a real one carries no per-call
# state — so the doubles it delegates to are reached the way the engine reaches
# the running rite.
_coding: ContextVar[CodingDouble | None] = ContextVar(
    "vekna_trial_coding", default=None
)
_shell: ContextVar[ShellDouble | None] = ContextVar("vekna_trial_shell", default=None)


def _reached(name: str, double: _DoubleT | None) -> _DoubleT:
    if double is None:
        msg = f"the {name} double is only reachable inside a Trial"
        raise TrialScriptError(msg)
    return double


class TrialCodingFocus(CodingFocusProtocol):
    @staticmethod
    async def run(
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply:
        double = _reached("coding", _coding.get())
        return await double.answer(call=call, on_delta=on_delta, gate=gate, ask=ask)


class TrialShellFocus(ShellFocusProtocol):
    @staticmethod
    async def run(
        call: ShellCall, *, on_line: Callable[[str], None] | None
    ) -> ShellReply:
        return _reached("shell", _shell.get()).answer(call, on_line=on_line)


@contextlib.contextmanager
def doubles_bound(*, coding: CodingDouble, shell: ShellDouble) -> Iterator[None]:
    tokens = (_coding.set(coding), _shell.set(shell))
    try:
        yield
    finally:
        _coding.reset(tokens[0])
        _shell.reset(tokens[1])
