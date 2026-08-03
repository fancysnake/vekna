from pydantic import BaseModel

from vekna.lexicon import NoComponents, Transition, goto, ritual
from vekna.lexicon._pacts import Ritual, Step


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
