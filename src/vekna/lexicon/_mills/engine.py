import asyncio
import contextlib
import traceback
from collections import Counter
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from itertools import starmap
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, JsonValue

from vekna.lexicon._mills._annotations import _failure_of
from vekna.lexicon._mills.ledger import Ledger
from vekna.lexicon._pacts import (
    Channel,
    CodingFocusProtocol,
    Done,
    ErrorInfo,
    FocusMissingError,
    Goto,
    RiteBegan,
    RiteEnded,
    RiteEvent,
    RiteRef,
    RiteStreamed,
    Ritual,
    RitualDefinitionError,
    RitualError,
    RitualSource,
    ShellFocusProtocol,
    Step,
    StepBoundaryError,
    StepBudgetExceededError,
    StringOutput,
    Transition,
)
from vekna.wire import RiteEndStatus

_FocusT = TypeVar("_FocusT")
_REPLAYED = "(from the journal — this rite already ran)"


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
        summary: str | None = None,
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
                summary=summary,
            )
        )
        return rite_id

    def rite_delta(self, rite_id: str, delta: str) -> None:
        self._append(RiteStreamed(rite_id=rite_id, delta=delta))

    def rite_finished(
        self,
        rite_id: str,
        *,
        status: RiteEndStatus = "ok",
        result: JsonValue | None = None,
        error: str | None = None,
    ) -> None:
        self._append(
            RiteEnded(
                rite_id=rite_id,
                status=status,
                result=result,
                finished_at=self._clock(),
                error=error,
            )
        )

    @property
    def events(self) -> list[RiteEvent]:
        return list(self._events)


NAMESPACE_SEPARATOR = ":"


def _qualified(namespace: str, name: str) -> str:
    return f"{namespace}{NAMESPACE_SEPARATOR}{name}" if namespace else name


# Keyed by (namespace, name): "" for the project's own, the tome's for a
# tome's, so two libraries whose authors never agreed on names need not have.
# A collision is only ever within one namespace, and every one is raised
# together: a library overlapping on two names would otherwise cost a cast per
# name. The same ritual arriving twice is not one — a package is swept module
# by module, and a submodule that reaches a sibling's ritual imports it,
# handing the sweep that ritual once per module that names it.
class Compendium:
    def __init__(self, shelves: Iterable[tuple[str, RitualSource]]) -> None:
        self._known: dict[tuple[str, str], Ritual] = {}
        origins: dict[tuple[str, str], str] = {}
        # Once per rival, which is swept again by every sibling that imports it.
        collisions: dict[tuple[str, str, int], str] = {}
        for namespace, source in shelves:
            for found in source.rituals:
                key = (namespace, found.name)
                if (first := self._known.get(key)) is None:
                    # Qualified once, so the hello, the max_steps refusal and
                    # the graph's diagnostics all say which `review` ran.
                    name = _qualified(*key)
                    self._known[key] = (
                        found if found.name == name else replace(found, name=name)
                    )
                    origins[key] = source.origin
                elif first.run is not found.run:
                    collisions.setdefault(
                        (*key, id(found.run)),
                        f"  ritual {_qualified(*key)!r} — declared in both "
                        f"{origins[key]} and {source.origin}",
                    )
        if collisions:
            lines = ["name collisions:", *collisions.values()]
            raise RitualDefinitionError("\n".join(lines))

    def ritual(self, name: str) -> Ritual:
        return self._known[self._resolve(name)]

    # The project's own first, then tome by tome.
    def names(self) -> list[str]:
        return list(starmap(_qualified, sorted(self._known)))

    # A qualified name resolves exactly. A bare one is the project's own if
    # there is one, else the one tome's that offers it: the prefix is for
    # telling two apart, not ceremony.
    def _resolve(self, name: str) -> tuple[str, str]:
        namespace, _, bare = name.rpartition(NAMESPACE_SEPARATOR)
        if (key := (namespace, bare)) in self._known:
            return key
        offered = [key for key in sorted(self._known) if key[0] and key[1] == name]
        if len(offered) == 1:
            return offered[0]
        if offered:
            candidates = ", ".join(starmap(_qualified, offered))
            msg = f"ritual {name!r} is ambiguous: {candidates}"
            raise RitualDefinitionError(msg)
        msg = f"no ritual named {name!r}"
        # A typo and an empty library are the same message otherwise, and
        # they want opposite things done about them.
        if known := self.names():
            msg = f"{msg} — known rituals: {', '.join(known)}"
        raise RitualDefinitionError(msg)


# A payload class is a step's identity, so this is the routing table: what a
# step returns is looked up here to find what runs next. Process-level and
# filled at decoration, like a `FocusSlot`, because the trial drives a ritual
# with no compendium in hand. A step's name routes nothing, so two rituals may
# each have a `measure`; two steps taking one class is the collision.
_steps: dict[type[BaseModel], Step] = {}


# Every payload checked before any is written: a step admitting `Lint | Coverage`
# whose second class collides would otherwise leave the first registered to a
# step this refused, and the sweep swallows the error and carries on.
def register_step(the_step: Step) -> None:
    for payload in the_step.payloads:
        if (first := _steps.get(payload)) is not None and first is not the_step:
            msg = (
                f"{payload.__name__} is the payload of both step {first.name!r} "
                f"and step {the_step.name!r} — one payload class, one step"
            )
            raise RitualDefinitionError(msg)
    _steps.update(dict.fromkeys(the_step.payloads, the_step))


def step_taking(payload: type[BaseModel]) -> Step | None:
    return _steps.get(payload)


# Steps decorated inside the block are forgotten at its end. A test that
# declares a throwaway step per case would otherwise hand the same payload
# class to a second step on the next case, which is the collision above — and
# steps declared at module level, before the block, are kept.
@contextlib.contextmanager
def steps_scope() -> Generator[None]:
    kept = dict(_steps)
    try:
        yield
    finally:
        _steps.clear()
        _steps.update(kept)


# Exact class, not isinstance: a subclass is not an edge the graph can draw, so
# it is not one the engine takes.
def step_for(transition: BaseModel) -> Step:
    if (found := _steps.get(type(transition))) is None:
        msg = f"no step takes {type(transition).__name__}"
        raise StepBoundaryError(msg)
    return found


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
# What stands here is an instance, so a Focus may carry state — which is what a
# test double is.
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
    def scope(self, focus: _FocusT) -> Generator[None]:
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


# What a rite leaves its opener: the id it was journaled under, and what its
# body raised, if it did.
@dataclass
class OpenedRite:
    rite_id: str
    error: ErrorInfo | None = None


# The one place a rite is opened and closed. A rite whose body raises is
# journaled with status="error" — steps and mediums alike, which is the whole
# reason both call sites share this.
@contextlib.asynccontextmanager
async def _rite(
    *, name: str, category: Literal["step", "medium"], summary: str | None = None
) -> AsyncGenerator[OpenedRite]:
    parent = current_rite()
    rite_id = parent.grimoire.rite_started(
        name=name, parent_id=parent.parent_id, category=category, summary=summary
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
    # Said out loud, because a rite that replayed and a rite that ran and
    # printed nothing look identical otherwise — and "did it really skip the
    # work?" is the question a resumed cast is watched for.
    if replay is not None:
        parent.grimoire.rite_delta(rite_id, _REPLAYED)
    opened = OpenedRite(rite_id)
    status: RiteEndStatus = "error"
    try:
        yield opened
        status = "ok"
    # Cut by a timeout, a race or Ctrl-C: neither done nor failed. What it had
    # produced by then is its deltas, already in the grimoire.
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    except Exception as raised:
        opened.error = ErrorInfo(
            type=type(raised).__name__,
            message=_said(raised),
            traceback="".join(traceback.format_exception(raised)),
        )
        raise
    finally:
        _current_rite.reset(token)
        # On the step alone: a medium that raised brings its step down with
        # the same message, and a cast that recovers prints no `cast failed:`
        # line, so the step is where it is said, once.
        parent.grimoire.rite_finished(
            rite_id,
            status=status,
            result=outcome.result,
            error=(
                opened.error.message
                if opened.error is not None and category == "step"
                else None
            ),
        )


# A bare `raise BoomError` has no message, and an empty error says nothing.
def _said(error: BaseException) -> str:
    return str(error) or type(error).__name__


def medium_rite(
    name: str, *, summary: str | None = None
) -> contextlib.AbstractAsyncContextManager[OpenedRite]:
    return _rite(name=name, category="medium", summary=summary)


# What a cast needs standing before a step can run. Extracted because the trial
# drives a single step without a ritual around it and needs the same ground: two
# copies of this would let the harness and the runtime drift apart, and the
# symptom would be a ritual test that passes while the real cast behaves
# differently.
@contextlib.contextmanager
def cast_context(
    *, grimoire: Grimoire, channel: Channel, ledger: Ledger | None = None
) -> Generator[None]:
    token = _current_rite.set(
        RiteContext(grimoire=grimoire, channel=channel, ledger=ledger)
    )
    try:
        yield
    finally:
        _current_rite.reset(token)


def recovery_for(payload: type[BaseModel]) -> Step | None:
    return _steps.get(_failure_of(payload))


# One step, run in its rite. A raise becomes the next transition when some step
# takes `Failure[<what entered>]`, and leaves unchanged when none does — which
# is what keeps a recovery step from catching its own raise: what entered it
# was a `Failure`. Not `BaseException`: cancellation and Ctrl-C are not a step
# failing. Only what the body raised is routed: a rite that never opened is
# vekna's failure, not the step's.
async def _taken(
    the_step: Step, payload: BaseModel | None, *, failures: Counter[Step]
) -> Transition:
    opened: OpenedRite | None = None
    try:
        async with _rite(name=the_step.name, category="step") as opened:
            return await the_step.run(payload)
    except Exception:
        if (
            opened is not None
            and opened.error is not None
            and payload is not None
            and recovery_for(type(payload)) is not None
        ):
            failures[the_step] += 1
            return _failure_of(type(payload))(
                error=opened.error,
                rite=RiteRef(rite_id=opened.rite_id, step=the_step.name),
                payload=payload,
                attempt=failures[the_step],
            )
        raise


async def run_cast(
    *,
    ritual: Ritual,
    components: BaseModel,
    grimoire: Grimoire,
    channel: Channel,
    ledger: Ledger | None = None,
) -> BaseModel | None:
    visits: Counter[Step] = Counter()
    failures: Counter[Step] = Counter()
    with cast_context(grimoire=grimoire, channel=channel, ledger=ledger):
        transition = await ritual.run(components)
        for _ in range(ritual.max_steps):
            if isinstance(transition, Done):
                break
            # ponytail: the legacy branch, named by the deletion note on `Goto`.
            if isinstance(transition, Goto):
                the_step, payload = transition.target, transition.payload
            else:
                the_step, payload = step_for(transition), transition
            visits[the_step] += 1
            if the_step.max_visits is not None and (
                visits[the_step] > the_step.max_visits
            ):
                msg = (
                    f"step {the_step.name!r} exceeded max_visits={the_step.max_visits}"
                )
                raise StepBudgetExceededError(msg)
            transition = await _taken(the_step, payload, failures=failures)
    if isinstance(transition, Done):
        return transition.result
    # Leaving the loop still mid-flight means the budget ran out, not that the
    # ritual finished — the only reason the check appears twice.
    msg = f"ritual {ritual.name!r} exceeded max_steps={ritual.max_steps}"
    raise StepBudgetExceededError(msg)
