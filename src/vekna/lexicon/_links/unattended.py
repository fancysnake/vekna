from collections.abc import Mapping, Sequence

from typing_extensions import override

from vekna.lexicon._pacts import Channel, UnattendedPromptError


# What stands in for the terminal when nobody is at it: every question is
# refused where it is asked, naming it, rather than dying at the third empty
# line of a stdin nobody writes to.
class UnattendedChannel(Channel):
    attended = False

    @override
    async def decide(
        self,
        *,
        prompt: str,
        options: Sequence[str] | None = None,
        free: bool = False,
        reactions: Mapping[str, str] | None = None,
    ) -> str:
        del options, free, reactions
        msg = f"unattended cast refused to ask: {prompt}"
        raise UnattendedPromptError(msg)
