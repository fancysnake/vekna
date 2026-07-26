import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import UnionType
from typing import Annotated, Literal, Protocol

from pydantic import AfterValidator, AnyUrl, BaseModel, ConfigDict, JsonValue


# Component types — the typed values on a ritual's external interface. They are
# boundary contracts, so they live here; that their validators touch the
# filesystem is inherent to what `File` and `Directory` mean.
def _existing_file(path: Path) -> Path:
    if not path.is_file():
        msg = f"not a readable file: {path}"
        raise ValueError(msg)
    return path


def _existing_directory(path: Path) -> Path:
    if not path.is_dir():
        msg = f"not a directory: {path}"
        raise ValueError(msg)
    return path


def _nonempty_git_ref(value: str) -> str:
    if not value.strip():
        msg = "git ref must be non-empty"
        raise ValueError(msg)
    return value


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class TextSpec:
    multiline: bool = False


File = Annotated[Path, AfterValidator(_existing_file)]
Directory = Annotated[Path, AfterValidator(_existing_directory)]
Text = Annotated[str, TextSpec()]
Url = AnyUrl
GitRef = Annotated[str, AfterValidator(_nonempty_git_ref)]


# The grimoire's own vocabulary, not the daemon's. These carry no `cast_id`:
# correlating events to a cast is a transport concern, and in one process there
# is one cast. `vekna.wire` projects these onto the socket at 0.6.0; keeping the
# two apart is what lets either change without the other.
@dataclass(frozen=True)
class RiteBegan:
    rite_id: str
    parent_id: str | None
    name: str
    category: Literal["step", "medium"]
    started_at: datetime


@dataclass(frozen=True)
class RiteStreamed:
    rite_id: str
    delta: str


# `result` is JSON-shaped because 0.6.0 persists the grimoire to a durable
# journal — a real requirement, not the transport leaking back in.
@dataclass(frozen=True)
class RiteEnded:
    rite_id: str
    status: Literal["ok", "error"]
    result: JsonValue | None
    finished_at: datetime


RiteEvent = RiteBegan | RiteStreamed | RiteEnded


# What loading a ritual source yields. The loader reaches the filesystem, so it
# lives in `_links`, which may not import the compendium in `_mills` — it hands
# back what it found and `_inits` registers it.
@dataclass(frozen=True)
class RitualSource:
    rituals: list["Ritual"]
    steps: list["Step"]


class Channel(Protocol):
    async def decide(
        self, *, prompt: str, options: Sequence[str] | None = None, free: bool = False
    ) -> str: ...


GateFn = Callable[[str], Awaitable[bool]]

# The agent's own question, mid-rite: free text when no options are offered.
AskFn = Callable[[str, Sequence[str] | None], Awaitable[str]]


@dataclass(frozen=True)
class CodingCall:
    prompt: str
    model: str | None
    system: str | None
    cwd: str | None
    output_schema: dict[str, JsonValue] | None
    focus_options: BaseModel | None


# Typed and closed, not a loose telemetry dict: a focus that spelled a key
# differently used to lose the field silently on the way into CodingResult.
class FocusReply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    session_id: str | None = None
    num_turns: int | None = None
    cost_usd: float | None = None


class CodingFocusProtocol(Protocol):
    async def run(
        self,
        call: CodingCall,
        *,
        on_delta: Callable[[str], None],
        gate: GateFn | None,
        ask: AskFn,
    ) -> FocusReply: ...


class RitualError(Exception):
    pass


class StepBudgetExceededError(RitualError):
    pass


class RitualDefinitionError(RitualError):
    pass


class StepBoundaryError(RitualError):
    pass


class RitualBoundaryError(RitualError):
    pass


class StandalonePromptError(RitualError):
    pass


class FocusMissingError(RitualError):
    pass


@dataclass(frozen=True)
class Done:
    result: BaseModel | None = None


# `source` is the decorated function's own source text, captured at definition
# time so `rituals show` can read the step graph off it. None when the function
# was built dynamically and has no source to read.
@dataclass(frozen=True)
class Step:
    name: str
    run: Callable[[BaseModel | None], Awaitable["Transition"]]
    input_type: type[BaseModel] | UnionType
    source: str | None = None


@dataclass(frozen=True)
class Goto:
    target: Step
    payload: BaseModel | None = None


Transition = Goto | Done


# A ritual declares its components as a model, so one that needs nothing would
# otherwise open with an empty class of its own. This is that class, written
# once.
class NoComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Ritual:
    name: str
    components: type[BaseModel]
    run: Callable[[BaseModel], Awaitable[Transition]]
    max_steps: int
    source: str | None = None


# A transition carries a pydantic model or nothing. The annotations alone would
# not hold: mypy sees `src/`, and a transition is written in the author's
# rituals.py, which it never reads.
def _checked(value: object, *, kind: str) -> BaseModel | None:
    if value is None or isinstance(value, BaseModel):  # type: ignore [misc]
        return value
    msg = f"{kind} takes a pydantic model or nothing, got {type(value).__name__}"
    raise RitualBoundaryError(msg)


def goto(target: Step, payload: BaseModel | None = None) -> Goto:
    return Goto(target=target, payload=_checked(payload, kind="goto"))


def done(result: BaseModel | None = None) -> Done:
    return Done(result=_checked(result, kind="done"))


# Unknown keys are an error: a misspelt `module = [...]` would otherwise load
# nothing and leave the next cast to fail with "no ritual named ...". The
# top-level table stays open — `[locks]` lands at 0.5.0.
class RitualsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[str] = []
    modules: list[str] = []


class Config(BaseModel):
    rituals: RitualsConfig = RitualsConfig()


class StringOutput(BaseModel):
    output: str


class BaseFocus:
    pass
