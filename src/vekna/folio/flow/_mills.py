from collections.abc import Sequence
from typing import Literal, TypeVar, overload

from vekna.lexicon import current_rite, medium, record_result, replayed

# An answer is one of the options it was offered — the channel returns a member
# or raises, never a string of its own — so a ritual offering
# `Literal["fix", "file", "ignore"]` gets that back rather than a bare `str` it
# would have to re-validate. Offering a plain `list[str]` still answers `str`.
_OptionT = TypeVar("_OptionT", bound=str)


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
        str(prior)
        if prior is not None
        else await current_rite().channel.decide(
            prompt=prompt, options=options, free=free
        )
    )
    record_result(answer)
    if options is None and not free:
        return answer == "yes"
    return answer
