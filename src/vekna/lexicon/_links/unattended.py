from collections.abc import Sequence

from typing_extensions import override

from vekna.lexicon._pacts import Channel, UnattendedPromptError


# What stands in for the terminal when nobody is at it: every question is
# refused where it is asked, naming it, rather than dying at the third empty
# line of a stdin nobody writes to.
class UnattendedChannel(Channel):
    @override
    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str:
        del options, free
        msg = f"unattended cast refused to ask: {prompt}"
        raise UnattendedPromptError(msg)
