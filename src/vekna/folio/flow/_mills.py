from collections.abc import Sequence
from typing import Literal, TypeVar, overload

from pydantic import JsonValue

from vekna.lexicon import RitualError, current_rite, medium, record_result, replayed

# An answer is one of the options it was offered — the channel returns a member
# or raises, never a string of its own — so a ritual offering
# `Literal["fix", "file", "ignore"]` gets that back rather than a bare `str` it
# would have to re-validate. Offering a plain `list[str]` still answers `str`.
_OptionT = TypeVar("_OptionT", bound=str)
_BOOLEAN = ("yes", "no")


# The live path has a guarantee the journal cannot carry: the channel answers
# with one of the options or raises. A ritual whose options changed since the
# interrupted cast would otherwise replay into a value its own `Literal` says
# cannot exist, and the caller would match on it. Refusing to resume beats that.
# A bare `decide` offers yes and no and is read for truth, so anything else off
# the journal comes back `False` — a recorded yes answered as a no, silently,
# which is the one way this can be wrong without anybody finding out. Free text
# is the case with nothing to check against: whatever was typed is the answer.
def _recorded(prior: JsonValue, *, options: Sequence[str] | None, free: bool) -> str:
    if not isinstance(prior, str):
        msg = f"the journaled answer {prior!r} is not text"
        raise RitualError(msg)
    offered = _BOOLEAN if options is None and not free else options
    if offered is not None and prior not in offered:
        msg = f"the journaled answer {prior!r} is not one of: {', '.join(offered)}"
        raise RitualError(msg)
    return prior


@overload
async def decide(prompt: str) -> bool: ...
@overload
async def decide(prompt: str, *, options: Sequence[_OptionT]) -> _OptionT: ...
@overload
async def decide(prompt: str, *, free: Literal[True]) -> str: ...


@medium
async def decide(
    prompt: str, *, options: Sequence[str] | None = None, free: bool = False
) -> bool | str:
    # A question this cast already asked is not asked again: the operator
    # answered it before the interruption, and a resumed cast that re-asked
    # would be making them defend a decision they had already made.
    prior = replayed()
    answer = (
        _recorded(prior, options=options, free=free)
        if prior is not None
        else await current_rite().channel.decide(
            prompt=prompt, options=options, free=free
        )
    )
    record_result(answer)
    if options is None and not free:
        return answer == "yes"
    return answer
