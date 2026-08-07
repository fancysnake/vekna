from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

_AnswerT = TypeVar("_AnswerT")


# What a `decide` call offered, as it was offered. The prompt is what a pattern
# matches against; the options are what an answer is checked against.
@dataclass(frozen=True, kw_only=True)
class Asked:
    prompt: str
    options: Sequence[str] | None = None
    free: bool = False


# What a scripted agent does with its turn. `uses` are tools it reaches for —
# each one meets the gate the call declared, or no gate at all — and `asks` are
# questions it puts to the human mid-rite. Both are how a ritual's `gate_tools`
# and `ask_human` paths are reached without an agent behind them.
@dataclass(frozen=True, kw_only=True)
class CodingAnswer:
    text: str
    uses: Sequence[str] = ()
    asks: Sequence[str] = ()


# One scripted answer. `when` is a glob over the call's subject — the command
# for shell, the prompt for coding and decide — and None means "whoever asks
# next", which is the ordered queue. `always` is what a gate that stays green
# for the whole cast needs.
@dataclass(frozen=True, kw_only=True)
class Answer(Generic[_AnswerT]):
    value: _AnswerT
    when: str | None = None
    always: bool = False


# What a double asks of the thing holding its answers. The doubles stand where a
# Focus stands, so they may reach for a contract and not for the mill behind it;
# `_inits` hands each of them a `Script`.
class ScriptProtocol(Protocol, Generic[_AnswerT]):
    def add(self, answer: Answer[_AnswerT]) -> None: ...

    def take(self, subject: str) -> _AnswerT: ...


class TrialError(Exception):
    pass


# Raised rather than defaulted. A double that invented an exit code would send
# a ritual down a branch nobody scripted and report the result as a pass.
class TrialScriptError(TrialError):
    pass
