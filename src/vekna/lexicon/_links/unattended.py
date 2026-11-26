from typing_extensions import override

from vekna.lexicon._pacts import Channel, Question, UnattendedPromptError


# What stands in for the terminal when nobody is at it: every question is
# refused where it is asked, naming it, rather than dying at the third empty
# line of a stdin nobody writes to.
class UnattendedChannel(Channel):
    attended = False

    @override
    async def decide(self, question: Question) -> str:
        msg = f"unattended cast refused to ask: {question.prompt}"
        raise UnattendedPromptError(msg)
