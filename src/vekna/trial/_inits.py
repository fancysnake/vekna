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
    _rite,
    cast_context,
    run_cast,
)
from vekna.lexicon._pacts import GrimoireEvent, Ritual, Step, Transition

from ._links import (
    CodingDouble,
    DecideDouble,
    ShellDouble,
    TrialCodingFocus,
    TrialShellFocus,
    doubles_bound,
)
from ._mills import Recorder, Script
from ._pacts import TrialError

_ResultT = TypeVar("_ResultT")

_CAST_ID = "trial"


# A ritual test is an ordinary test, so the pair a test calls owns the loop.
# From inside a running one there is nothing to own, and the async pair is what
# that suite wants — said here rather than left to asyncio's own message, which
# names neither. `close()` keeps the never-awaited warning off a coroutine this
# refuses to drive.
def _driven(coro: Coroutine[str, str, _ResultT]) -> _ResultT:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    coro.close()
    msg = (
        "cast() and walk() own the event loop — call cast_async() or walk_async() "
        "from inside a running one"
    )
    raise TrialError(msg)


class Trial:
    def __init__(self) -> None:
        self.coding = CodingDouble(Script(kind="coding"))
        self.shell = ShellDouble(Script(kind="shell"))
        self.decide = DecideDouble(Script(kind="decide"))
        self.result: BaseModel | None = None
        self._recorder = Recorder()
        self._installed = contextlib.ExitStack()
        self._active = False

    def __enter__(self) -> Self:
        self._installed.enter_context(CODING_FOCUS.scope(TrialCodingFocus))
        self._installed.enter_context(SHELL_FOCUS.scope(TrialShellFocus))
        self._installed.enter_context(
            doubles_bound(coding=self.coding, shell=self.shell)
        )
        self._active = True
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self._installed.close()
        finally:
            self._active = False

    # Outside the block nothing is installed, and `shell()` falls back to its
    # own default — which is bash. A test that forgot the `with` would run the
    # command for real, record nothing on the double, and pass. Refused here
    # rather than discovered by a repository that lost a branch to it.
    def _entered(self) -> None:
        if not self._active:
            msg = "a Trial answers only inside its `with` block"
            raise TrialError(msg)

    @property
    def steps(self) -> list[str]:
        return self._recorder.steps

    @property
    def deltas(self) -> list[str]:
        return self._recorder.deltas

    @property
    def statuses(self) -> list[str]:
        return self._recorder.statuses

    @property
    def events(self) -> list[GrimoireEvent]:
        return list(self._recorder.events)

    def _grimoire(self) -> Grimoire:
        return Grimoire(cast_id=_CAST_ID, on_event=self._recorder.record)

    def cast(self, ritual: Ritual, components: BaseModel) -> BaseModel | None:
        return _driven(self.cast_async(ritual, components))

    async def cast_async(
        self, ritual: Ritual, components: BaseModel
    ) -> BaseModel | None:
        self._entered()
        self.result = await run_cast(
            ritual=ritual,
            components=components,
            grimoire=self._grimoire(),
            channel=self.decide,
        )
        return self.result

    def walk(self, step: Step, payload: BaseModel | None = None) -> Transition:
        return _driven(self.walk_async(step, payload))

    # Not a throwaway ritual around `run_cast`, which answers with the cast's
    # result and swallows every transition on the way: the transition is the
    # whole question a one-step test asks. The ground a cast stands on is the
    # same `cast_context`, so what `run_cast` grows the walk grows with it.
    async def walk_async(
        self, step: Step, payload: BaseModel | None = None
    ) -> Transition:
        self._entered()
        with cast_context(grimoire=self._grimoire(), channel=self.decide):
            async with _rite(name=step.name, category="step"):
                return await step.run(payload)
