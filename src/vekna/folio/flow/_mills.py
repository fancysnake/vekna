from collections.abc import Sequence
from typing import Literal, TypeVar, overload

from vekna.lexicon import current_rite, medium

# An answer is one of the options it was offered — the channel returns a member
# or raises, never a string of its own — so a ritual offering
# `Literal["fix", "file", "ignore"]` gets that back rather than a bare `str` it
# would have to re-validate. Offering a plain `list[str]` still answers `str`.
# There is deliberately no `options` + `free` overload: suggestion-mode is the
# agent's path through `Channel.decide`, and opening it here would let a ritual
# offer `Literal["fix", "stop"]` and be handed something else.
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
    answer = await current_rite().channel.decide(
        prompt=prompt, options=options, free=free
    )
    if options is None and not free:
        return answer == "yes"
    return answer
