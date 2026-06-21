from collections.abc import Sequence

from vekna.lexicon import current_rite, medium


@medium
async def decide(*, prompt: str, options: Sequence[str]) -> str:
    return await current_rite().channel.decide(prompt=prompt, options=options)


@medium
async def approve(*, prompt: str) -> bool:
    return await current_rite().channel.approve(prompt=prompt)


@medium
async def ask(*, prompt: str, choices: Sequence[str] | None = None) -> str:
    return await current_rite().channel.ask(prompt=prompt, choices=choices)
