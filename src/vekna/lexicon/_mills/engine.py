import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, JsonValue

from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import (
    Channel,
    CodingFocusProtocol,
    Done,
    FocusMissingError,
    RiteBegan,
    RiteEnded,
    RiteEvent,
    RiteStreamed,
    Ritual,
    RitualDefinitionError,
    RitualError,
    ShellFocusProtocol,
    Step,
    StepBudgetExceededError,
    StringOutput,
)

_FocusT = TypeVar("_FocusT")


def _now() -> datetime:
    return datetime.now(tz=UTC)


class Grimoire:
    def __init__(
        self,
        *,
        cast_id: str,
        clock: Callable[[], datetime] = _now,
        on_event: Callable[[RiteEvent], None] | None = None,
    ) -> None:
        self.cast_id = cast_id
        self._clock = clock
        self._on_event = on_event
        self._events: list[RiteEvent] = []
        self._counter = 0

    def _append(self, event: RiteEvent) -> None:
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)

    def rite_started(
        self,
        *,
        name: str,
        parent_id: str | None = None,
        category: Literal["step", "medium"] = "step",
    ) -> str:
        self._counter += 1
        rite_id = f"r{self._counter}"
        self._append(
            RiteBegan(
                rite_id=rite_id,
                parent_id=parent_id,
                name=name,
                category=category,
                started_at=self._clock(),
            )
        )
        return rite_id

    def rite_delta(self, rite_id: str, delta: str) -> None:
        self._append(RiteStreamed(rite_id=rite_id, delta=delta))

    def rite_finished(
        self,
        rite_id: str,
        *,
        status: Literal["ok", "error"] = "ok",
        result: JsonValue | None = None,
    ) -> None:
        self._append(
            RiteEnded(
                rite_id=rite_id, status=status, result=result, finished_at=self._clock()
            )
        )

    @property
    def events(self) -> list[RiteEvent]:
        return list(self._events)


_DeclaredT = TypeVar("_DeclaredT", Ritual, Step)


# Rituals and steps are registered the same way: by name, remembering which
# module declared each, so a genuine collision says which two rather than
# leaving the author to guess. The *same* object arriving twice is not one — a
# package is swept module by module, and a submodule that reaches a sibling's
# ritual or step imports it, handing the sweep that object once per module that
# names it.
class _Declarations(Generic[_DeclaredT]):
    def __init__(self, kind: str) -> None:
        self._kind = kind
        self._known: dict[str, _DeclaredT] = {}
        self._origins: dict[str, str] = {}

    # `name` is not a parameter: `_DeclaredT` is a Ritual or a Step, and both
    # carry the name the caller would otherwise be handing back.
    def add(self, declared: _DeclaredT, *, origin: str | None) -> None:
        if (first := self._known.get(declared.name)) is not None:
            if first is declared:
                return
            raise RitualDefinitionError(self._collision(declared.name, origin))
        self._known[declared.name] = declared
        if origin is not None:
            self._origins[declared.name] = origin

    def get(self, name: str) -> _DeclaredT | None:
        return self._known.get(name)

    def names(self) -> list[str]:
        return sorted(self._known)

    def _collision(self, name: str, origin: str | None) -> str:
        msg = f"{self._kind} {name!r} is already registered"
        first = self._origins.get(name)
        if first is None or origin is None:
            return msg
        return f"{msg} — declared in both {first} and {origin}"


class Compendium:
    def __init__(self) -> None:
        self._rituals: _Declarations[Ritual] = _Declarations("ritual")
        self._steps: _Declarations[Step] = _Declarations("step")

    def register(self, ritual: Ritual, *, origin: str | None = None) -> None:
        self._rituals.add(ritual, origin=origin)

    # Once a name collision was worth no more than the first definition winning
    # — every step was in one file, where a duplicate is a visible mistake.
    # Across the submodules of a package `measure` is a natural name twice, and
    # the loser vanishing means `rituals show` drawing the other ritual's step.
    def register_step(self, the_step: Step, *, origin: str | None = None) -> None:
        self._steps.add(the_step, origin=origin)

    def step(self, name: str) -> Step | None:
        return self._steps.get(name)

    def ritual(self, name: str) -> Ritual:
        if (found := self._rituals.get(name)) is None:
            msg = f"no ritual named {name!r}"
            # A typo and an empty library are the same message otherwise, and
            # they want opposite things done about them.
            if known := self.names():
                msg = f"{msg} — known rituals: {', '.join(known)}"
            raise RitualDefinitionError(msg)
        return found

    def names(self) -> list[str]:
        return self._rituals.names()


# What a medium package offers the lexicon, which may not import it: the Focus
# it needs (and how to obtain one), plus an optional one-shot entry so `cast
# --prompt` can reach the medium without a second dynamic-import mechanism.
PromptRunner = Callable[[str], Awaitable[StringOutput]]


# A slot is a medium's name *and* the protocol whatever stands there must
# satisfy. A `str` key carries no type, which is what forced the registry this
# replaces to store `object` and every medium to cast back out of it — and a
# cast checks nothing, so a Focus whose `run` had the wrong shape reached the
# call site intact. Here the type travels with the name: `register` refuses what
# the medium could not call, and `resolve` hands back the protocol itself.
# A Focus holds no state and its `run` is static, so the class and an instance
# of it both satisfy the protocol; a folio may register either.
class FocusSlot(Generic[_FocusT]):
    def __init__(self, medium_name: str) -> None:
        self.medium_name = medium_name
        self._focus: _FocusT | None = None
        # Scoped installs are context-local, registrations are not. A registry
        # entry is the process saying what stands where; a scope is one caller
        # saying it for the duration of a block, and two callers may hold
        # overlapping blocks. Saving and restoring one attribute is only correct
        # while the blocks nest, which nothing makes them do — two trials in one
        # TaskGroup, and the first to exit puts back the second's focus.
        self._scoped: ContextVar[_FocusT | None] = ContextVar(
            f"vekna_focus_{medium_name}", default=None
        )
        self._hint: str | None = None
        _clearers.append(self.clear)

    def expect(self, *, hint: str) -> None:
        self._hint = hint

    def register(self, focus: _FocusT) -> None:
        self._focus = focus

    # A `default` is for a medium that can always answer for itself — `shell`
    # has bash whether or not anything registered. Raising is right for a focus
    # that may not be installed at all, and wrong for one that is the runtime.
    def resolve(self, *, default: _FocusT | None = None) -> _FocusT:
        if (scoped := self._scoped.get()) is not None:
            return scoped
        if self._focus is not None:
            return self._focus
        if default is not None:
            return default
        msg = f"no Focus registered for medium {self.medium_name!r}"
        if self._hint is not None:
            msg = f"{msg} — {self._hint}"
        raise FocusMissingError(msg)

    # Install for the duration of a block and put back exactly what was there,
    # an absence included. The slot had `register` and a wholesale `reset` and
    # nothing between them: a test double that reset would clobber a focus the
    # author registered, and one that only registered would leave itself
    # installed for whatever ran next.
    @contextlib.contextmanager
    def scope(self, focus: _FocusT) -> Iterator[None]:
        token = self._scoped.set(focus)
        try:
            yield
        finally:
            self._scoped.reset(token)

    # The hint as well as the focus: either one outliving the reset means a test
    # inherits registration it never made, and passes only in the company of
    # whichever test made it.
    def clear(self) -> None:
        self._focus = None
        self._hint = None


# Slots enrol themselves, so a medium added later is reset without anyone
# having to remember this list.
_clearers: list[Callable[[], None]] = []

CODING_FOCUS: FocusSlot[CodingFocusProtocol] = FocusSlot("coding")
SHELL_FOCUS: FocusSlot[ShellFocusProtocol] = FocusSlot("shell")

# A one-shot prompt is the same callable whichever medium offers it, so a name
# is all it needs to be keyed by.
_prompts: dict[str, PromptRunner] = {}


def offer_prompt(medium_name: str, run: PromptRunner) -> None:
    _prompts[medium_name] = run


def prompt_runner(medium_name: str) -> PromptRunner:
    try:
        return _prompts[medium_name]
    except KeyError:
        msg = f"medium {medium_name!r} offers no one-shot prompt"
        raise RitualError(msg) from None


def reset_registry() -> None:
    for clear in _clearers:
        clear()
    _prompts.clear()


@dataclass
class RiteOutcome:
    result: JsonValue | None = None


# A cast's threads of agent memory, by name. The vocabulary that decides which
# name a call means — and that some names are reserved — belongs to the medium;
# this only remembers. `latest` is what "carry on from the last call" resolves
# to, and every recorded reply moves it, named or not.
@dataclass
class SessionBook:
    latest: str | None = None
    _named: dict[str, str] = field(default_factory=dict)

    def named(self, name: str) -> str | None:
        return self._named.get(name)

    def record(self, session_id: str, *, name: str | None = None) -> None:
        self.latest = session_id
        if name is not None:
            self._named[name] = session_id


# One book per cast: `_rite` rebuilds the context with `replace`, which copies
# the reference, so every rite under a cast shares the book and no cast sees
# another's.
@dataclass(frozen=True, kw_only=True)
class RiteContext:
    grimoire: Grimoire
    channel: Channel
    parent_id: str | None = None
    outcome: RiteOutcome = field(default_factory=RiteOutcome)
    sessions: SessionBook = field(default_factory=SessionBook)
    # The interrupted cast's record, when this one is carrying it on, and what
    # this rite in particular already produced. Both None in a fresh cast, which
    # is every cast that was not resumed.
    ledger: Ledger | None = None
    replay: JsonValue | None = None


def record_result(value: JsonValue) -> None:
    current_rite().outcome.result = value


# What this rite produced the last time round, or None to do the work. Read by
# the medium rather than applied to it: only the medium knows how to turn its
# own recorded value back into what it returns, and `output=` makes coding's
# depend on the call site.
def replayed() -> JsonValue | None:
    return current_rite().replay


_current_rite: ContextVar[RiteContext | None] = ContextVar(
    "vekna_current_rite", default=None
)


def current_rite() -> RiteContext:
    if (rite := _current_rite.get()) is None:
        msg = "mediums can only be called inside a running cast"
        raise RitualError(msg)
    return rite


# Deltas need a rite to hang off. Steps and mediums both open one; a ritual
# body runs at the cast root, where there is none.
def _current_rite_id(rite: RiteContext) -> str:
    if (rite_id := rite.parent_id) is None:
        msg = "no rite is running — deltas belong to a step or a medium"
        raise RitualError(msg)
    return rite_id


# The one way a medium streams output into its own rite.
def emit_delta(text: str) -> None:
    rite = current_rite()
    rite.grimoire.rite_delta(_current_rite_id(rite), text)


# The one place a rite is opened and closed. A rite whose body raises is
# journaled with status="error" — steps and mediums alike, which is the whole
# reason both call sites share this.
@contextlib.asynccontextmanager
async def _rite(
    *, name: str, category: Literal["step", "medium"]
) -> AsyncIterator[None]:
    parent = current_rite()
    rite_id = parent.grimoire.rite_started(
        name=name, parent_id=parent.parent_id, category=category
    )
    outcome = RiteOutcome()
    # Looked up once, here, and only for mediums: a step's rite id is in the
    # same counter, and asking the ledger about one would spend it on a rite it
    # was never going to hold.
    replay = (
        parent.ledger.take(rite_id=rite_id, name=name)
        if parent.ledger is not None and category == "medium"
        else None
    )
    token = _current_rite.set(
        replace(parent, parent_id=rite_id, outcome=outcome, replay=replay)
    )
    finished = False
    try:
        yield
        finished = True
    finally:
        _current_rite.reset(token)
        parent.grimoire.rite_finished(
            rite_id, status="ok" if finished else "error", result=outcome.result
        )


def medium_rite(name: str) -> contextlib.AbstractAsyncContextManager[None]:
    return _rite(name=name, category="medium")


# What a cast needs standing before a step can run. Extracted because the trial
# drives a single step without a ritual around it and needs the same ground: two
# copies of this would let the harness and the runtime drift apart, and the
# symptom would be a ritual test that passes while the real cast behaves
# differently.
@contextlib.contextmanager
def cast_context(
    *, grimoire: Grimoire, channel: Channel, ledger: Ledger | None = None
) -> Iterator[None]:
    token = _current_rite.set(
        RiteContext(grimoire=grimoire, channel=channel, ledger=ledger)
    )
    try:
        yield
    finally:
        _current_rite.reset(token)


async def run_cast(
    *,
    ritual: Ritual,
    components: BaseModel,
    grimoire: Grimoire,
    channel: Channel,
    ledger: Ledger | None = None,
) -> BaseModel | None:
    with cast_context(grimoire=grimoire, channel=channel, ledger=ledger):
        transition = await ritual.run(components)
        for _ in range(ritual.max_steps):
            if isinstance(transition, Done):
                break
            async with _rite(name=transition.target.name, category="step"):
                transition = await transition.target.run(transition.payload)
    if isinstance(transition, Done):
        return transition.result
    # Leaving the loop still mid-flight means the budget ran out, not that the
    # ritual finished — the only reason the check appears twice.
    msg = f"ritual {ritual.name!r} exceeded max_steps={ritual.max_steps}"
    raise StepBudgetExceededError(msg)
