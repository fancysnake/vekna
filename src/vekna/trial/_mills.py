from fnmatch import fnmatchcase
from typing import Generic, TypeVar

from vekna.lexicon._pacts import RiteBegan, RiteEvent, RiteStreamed

from ._pacts import Answer, TrialScriptError

_AnswerT = TypeVar("_AnswerT")


def _describe(answer: Answer[_AnswerT]) -> str:
    where = "next in line" if answer.when is None else f"when={answer.when!r}"
    return f"{where} → {answer.value!r}"


# Matched answers win over the queue, because which of two concurrent calls
# arrives first is the scheduler's business — `merge_ready.gates` starts both
# gates in a TaskGroup, and a script keyed on arrival order would make that test
# flaky by construction. What no pattern claims still falls back to arrival
# order, which is what a single-call step wants to write.
class Script(Generic[_AnswerT]):
    def __init__(self, *, kind: str) -> None:
        self._kind = kind
        self._answers: list[Answer[_AnswerT]] = []

    def add(self, answer: Answer[_AnswerT]) -> None:
        self._answers.append(answer)

    def _matching(self, subject: str) -> Answer[_AnswerT] | None:
        for answer in self._answers:
            if answer.when is not None and fnmatchcase(subject, answer.when):
                return answer
        return next((one for one in self._answers if one.when is None), None)

    def take(self, subject: str) -> _AnswerT:
        if (answer := self._matching(subject)) is None:
            raise TrialScriptError(self._nothing_left(subject))
        if not answer.always:
            self._answers.remove(answer)
        return answer.value

    def _nothing_left(self, subject: str) -> str:
        msg = f"{self._kind} was called with {subject!r} and nothing answers it"
        if not self._answers:
            return f"{msg} — the script is empty"
        held = ", ".join(_describe(answer) for answer in self._answers)
        return f"{msg} — the script still holds: {held}"


# Everything the grimoire said, kept as it arrives. The step names are read off
# the same events rather than tracked separately: a step is a rite that began
# with category "step", and there is no second place for that to be wrong.
class Recorder:
    def __init__(self) -> None:
        self.events: list[RiteEvent] = []

    def record(self, event: RiteEvent) -> None:
        self.events.append(event)

    @property
    def steps(self) -> list[str]:
        return [
            event.name
            for event in self.events
            if isinstance(event, RiteBegan) and event.category == "step"
        ]

    @property
    def deltas(self) -> list[str]:
        return [event.delta for event in self.events if isinstance(event, RiteStreamed)]
