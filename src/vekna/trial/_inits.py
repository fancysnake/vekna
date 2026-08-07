import asyncio
import contextlib
from collections.abc import Coroutine
from types import TracebackType
from typing import Self, TypeVar

from pydantic import BaseModel

from vekna.lexicon._mills.engine import (
    CODING_FOCUS,
    SHELL_FOCUS,
    Grimoire,
    RiteContext,
    _current_rite,
    _rite,
    run_cast,
)
from vekna.lexicon._pacts import RiteEvent, Ritual, Step, Transition

from ._links import (
    CodingDouble,
    DecideDouble,
    ShellDouble,
    TrialCodingFocus,
    TrialShellFocus,
    doubles_bound,
)
from ._mills import Recorder
from ._pacts import TrialError

_ResultT = TypeVar("_ResultT")

_CAST_ID = "trial"


# A ritual test is an ordinary test, so the pair a test calls owns the loop.
# From inside a running one there is nothing to own, and the async pair is what
# that suite wants — said here rather than left to asyncio's own message, which
# names neither.
def _driven(coro: Coroutine[str, str, _ResultT], *, sync: str, other: str) -> _ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    msg = f"{sync}() owns the event loop — call {other}() from inside a running one"
    raise TrialError(msg)


class Trial:
    def __init__(self) -> None:
        self.coding = CodingDouble()
        self.shell = ShellDouble()
        self.decide = DecideDouble()
        self.result: BaseModel | None = None
        self._recorder = Recorder()
        self._installed = contextlib.ExitStack()

    def __enter__(self) -> Self:
        self._installed.enter_context(CODING_FOCUS.scope(TrialCodingFocus))
        self._installed.enter_context(SHELL_FOCUS.scope(TrialShellFocus))
        self._installed.enter_context(
            doubles_bound(coding=self.coding, shell=self.shell)
        )
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._installed.close()

    @property
    def steps(self) -> list[str]:
        return self._recorder.steps

    @property
    def deltas(self) -> list[str]:
        return self._recorder.deltas

    @property
    def events(self) -> list[RiteEvent]:
        return list(self._recorder.events)

    def _grimoire(self) -> Grimoire:
        return Grimoire(cast_id=_CAST_ID, on_event=self._recorder.record)

    def cast(self, ritual: Ritual, components: BaseModel) -> BaseModel | None:
        return _driven(
            self.cast_async(ritual, components), sync="cast", other="cast_async"
        )

    async def cast_async(
        self, ritual: Ritual, components: BaseModel
    ) -> BaseModel | None:
        self.result = await run_cast(
            ritual=ritual,
            components=components,
            grimoire=self._grimoire(),
            channel=self.decide,
        )
        return self.result

    def walk(self, step: Step, payload: BaseModel | None = None) -> Transition:
        return _driven(self.walk_async(step, payload), sync="walk", other="walk_async")

    # Not a throwaway ritual around `run_cast`, which answers with the cast's
    # result and swallows every transition on the way: the transition is the
    # whole question a one-step test asks. The rite is opened all the same, so
    # the step's mediums hang off it and `trial.steps` reads the same as a cast.
    async def walk_async(
        self, step: Step, payload: BaseModel | None = None
    ) -> Transition:
        token = _current_rite.set(
            RiteContext(grimoire=self._grimoire(), channel=self.decide)
        )
        try:
            async with _rite(name=step.name, category="step"):
                return await step.run(payload)
        finally:
            _current_rite.reset(token)
