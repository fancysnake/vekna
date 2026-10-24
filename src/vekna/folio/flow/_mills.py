from collections.abc import Sequence
from typing import Literal, TypeVar, overload

from pydantic import BaseModel, JsonValue, ValidationError

from vekna.lexicon import (
    CAST_QUEUE,
    CastFailedError,
    MediumBoundaryError,
    RitualError,
    allowed_answers,
    current_rite,
    medium,
    record_result,
    replayed,
)

# An answer is one of the options it was offered — the channel returns a member
# or raises, never a string of its own — so a ritual offering
# `Literal["fix", "file", "ignore"]` gets that back rather than a bare `str` it
# would have to re-validate. Offering a plain `list[str]` still answers `str`.
# There is deliberately no `options` + `free` overload: suggestion-mode is the
# agent's path through `Channel.decide`, and opening it here would let a ritual
# offer `Literal["fix", "stop"]` and be handed something else.
_OptionT = TypeVar("_OptionT", bound=str)


# The live path has a guarantee the journal cannot carry: the channel answers
# with one of the options or raises. A ritual whose options changed since the
# interrupted cast would otherwise replay into a value its own `Literal` says
# cannot exist, and the caller would match on it. Refusing to resume beats that.
# A bare `decide` offers yes and no and is read for truth, so anything else off
# the journal comes back `False` — a recorded yes answered as a no, silently,
# which is the one way this can be wrong without anybody finding out. What each
# call allows is `allowed_answers`, the same rule the channel and the trial
# double read.
def _recorded(prior: JsonValue, *, options: Sequence[str] | None, free: bool) -> str:
    if not isinstance(prior, str):
        msg = f"the journaled answer {prior!r} is not text"
        raise RitualError(msg)
    allowed = allowed_answers(options=options, free=free)
    if allowed is not None and prior not in allowed:
        msg = f"the journaled answer {prior!r} is not one of: {', '.join(allowed)}"
        raise RitualError(msg)
    return prior


@overload
async def decide(prompt: str) -> bool: ...
@overload
async def decide(prompt: str, *, options: Sequence[_OptionT]) -> _OptionT: ...
@overload
async def decide(prompt: str, *, free: Literal[True]) -> str: ...


@medium
async def decide(
    prompt: str, *, options: Sequence[str] | None = None, free: bool = False
) -> bool | str:
    # An empty `options` is a question with no answer in it: the live path would
    # quietly fall through to yes/no and the journal would then refuse what it
    # recorded. A list that computed to nothing is a bug in the step, so it
    # stops here rather than becoming a different question.
    if options is not None and not options:
        msg = "decide(options=...) needs at least one option"
        raise MediumBoundaryError(msg)
    # A question this cast already asked is not asked again: the operator
    # answered it before the interruption, and a resumed cast that re-asked
    # would be making them defend a decision they had already made.
    prior = replayed()
    answer = (
        _recorded(prior, options=options, free=free)
        if prior is not None
        else await current_rite().channel.decide(
            prompt=prompt, options=options, free=free
        )
    )
    record_result(answer)
    if options is None and not free:
        return answer == "yes"
    return answer


_ModelT = TypeVar("_ModelT", bound=BaseModel)


# The id is recorded, so a resumed cast that enqueued already does not queue
# the child a second time.
@medium
async def enqueue(ritual: str, components: BaseModel) -> str:
    if (prior := replayed()) is not None:
        if not isinstance(prior, str):
            msg = f"the journaled cast id {prior!r} is not text"
            raise RitualError(msg)
        cast_id = prior
    else:
        cast_id = await CAST_QUEUE.resolve().enqueue(
            ritual=ritual, components=components
        )
    record_result(cast_id)
    return cast_id


# Two mediums and not one: a single rite that replayed its result would skip the
# enqueue inside it, and every rite after would be numbered off the record. So
# a cast interrupted mid-wait replays the enqueue and waits on the same child.
@overload
async def await_cast(ritual: str, components: BaseModel) -> JsonValue: ...
@overload
async def await_cast(
    ritual: str, components: BaseModel, *, output: type[_ModelT]
) -> _ModelT: ...


async def await_cast(
    ritual: str, components: BaseModel, *, output: type[BaseModel] | None = None
) -> JsonValue | BaseModel:
    cast_id = await enqueue(ritual, components)
    result = await awaited(cast_id)
    if output is None:
        return result
    try:
        return output.model_validate(result)
    except ValidationError as error:
        msg = f"cast {cast_id} returned what does not validate as {output!r}: {error}"
        raise RitualError(msg) from error


# Gives up this cast's process slot until the child ends. A child that ended
# with nothing to say has nothing to replay, and is asked about again.
@medium
async def awaited(cast_id: str) -> JsonValue:
    if (prior := replayed()) is not None:
        record_result(prior)
        return prior
    ended = await CAST_QUEUE.resolve().await_end(cast_id)
    if ended.status != "ok":
        reason = f": {ended.detail}" if ended.detail else ""
        msg = f"cast {cast_id} ended {ended.status}{reason}"
        raise CastFailedError(msg)
    record_result(ended.result)
    return ended.result
