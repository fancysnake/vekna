from collections.abc import Sequence
from typing import Literal, overload

from vekna.lexicon import current_rite, medium


@overload
async def decide(prompt: str) -> bool: ...
@overload
async def decide(prompt: str, *, options: Sequence[str]) -> str: ...
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
