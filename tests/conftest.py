import io

from pydantic import BaseModel

from vekna.lexicon import NoComponents, Transition, goto, ritual
from vekna.lexicon._pacts import Ritual, Step


# A notification is an escape sequence written only to a tty, and neither
# pytest's capture nor a plain StringIO is one. Both suites need a stream that
# says it is a terminal.
class Tty(io.StringIO):
    @staticmethod
    def isatty() -> bool:
        return True


# Most tests need a ritual only to reach the step they are actually about — an
# entrypoint that names one target and hands it a payload, which written out is
# the same three lines every time. `name` stays a parameter because it reaches
# the rendered rite tree, so a test asserting on output still gets to say what
# the ritual is called.
def entry(*, name: str = "r", target: Step, payload: BaseModel) -> Ritual:
    @ritual(name)
    def _enter(_: NoComponents) -> Transition:
        return goto(target, payload)

    return _enter
